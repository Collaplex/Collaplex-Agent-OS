/* Collaplex 网页版前端。
 *
 * md 渲染这套是照 2026-10-07 拆的那 18 家 AI 前端来的, 四条硬规矩:
 *   ① 别自己正则切 markdown —— 每帧把整个 buffer 丢给 CommonMark parser,
 *      未闭合的围栏/表格/公式由它容错(这样流式时永远不会吐裸 ``` );
 *   ② 块级复用 DOM 节点 —— 一个字节没变的块原样留着, 不重建 → 不重排、不闪;
 *   ③ 新出现的块淡入一次; 这轮流完给根加 .md-完成, CSS 里把动画全关(历史消息零重排);
 *   ④ 代码高亮/复制按钮/表格外壳只对"变了的块"做, 流式期间也高亮。
 * 渲染一帧只跑一次(增量先攒着, requestAnimationFrame 合并)。
 */
(() => {
  'use strict';

  // ★ 软件"启动"该先站到启动页 —— 之前 cli 直接把浏览器开到 /, 一开门就是主页面,
  //   启动页等于白做(2026-10-08 老板报的)。这一层拦"自己敲 / 或从收藏夹进来"的:
  //   没走过启动页就把人送去 /启动。走完一次在本次会话里留痕, 之后刷新/切节不再拦。
  //   就想直接看主页面: 地址后面加 ?直进=1
  // ★ 参数里有中文, 浏览器会把它编码成 %E7%9B%B4%E8%BF%9B=1 —— 得先解回来再比
  if (location.pathname === '/' && !decodeURIComponent(location.search).includes('直进=1')
      && sessionStorage.getItem('已过启动页') !== '1') {
    location.replace('/启动');
    return;
  }

  const 流 = document.getElementById('流');
  const 空态 = document.getElementById('空态');
  const 问框 = document.getElementById('问框');
  const 问表 = document.getElementById('问表');
  const 发送 = document.getElementById('发送');
  const 状态行 = document.getElementById('状态行');
  const 服务灯 = document.getElementById('服务灯');
  const 模型名 = document.getElementById('模型名');
  const 统计 = document.getElementById('统计');
  const 到底 = document.getElementById('到底');
  const 侧历史 = document.getElementById('历史');
  const 设置钮 = document.getElementById('设置钮');
  const 收栏钮 = document.getElementById('收栏钮');
  const 设置页 = document.getElementById('设置页');
  const 页眉 = document.getElementById('页眉');
  const 底栏 = document.getElementById('底栏');
  const 对话区 = document.getElementById('对话区');
  const 哨兵 = document.getElementById('哨兵');
  let 忙 = false;
  let 在看设置 = false;
  let 当前名 = '';        // 顶栏显示: 正在看的那条历史的问题(新对话时清空)

  // ─────────────────────────── 1. markdown parser ───────────────────────────

  const md = window.markdownit({
    html: false,      // 不放开原始 HTML —— 净化只是兜底, 第一道门先关着
    linkify: true,
    breaks: false,
    typographer: false
  });

  const 转义 = (文本) => 文本.replace(/[&<>]/g, (符) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[符]));
  const 渲公式 = (源, 块) => {
    try {
      return window.katex.renderToString(源, {
        displayMode: 块, output: 'html', throwOnError: false, strict: 'ignore'
      });
    } catch (错) {
      return '<code class="数学错">' + 转义(源) + '</code>';
    }
  };

  // $...$ : 找不到闭合的 $ 就当普通文本(流式时半截公式不闪)
  md.inline.ruler.after('escape', '数学行内', (状态) => {
    if (状态.src.charCodeAt(状态.pos) !== 0x24) return false;
    const 起 = 状态.pos;
    let i = 起 + 1;
    while (i < 状态.posMax) {
      const 字 = 状态.src[i];
      if (字 === '\\') { i += 2; continue; }
      if (字 === '$') {
        const 内容 = 状态.src.slice(起 + 1, i);
        if (内容.length && !/^\s/.test(内容) && !/\s$/.test(内容)) {
          状态.pos = i + 1;
          状态.push('math_inline', 'math', 0).content = 内容;
          return true;
        }
      }
      i += 1;
    }
    return false;
  });

  // $$ 独占一行的块级公式: 收尾没到就当普通段落渲染
  md.block.ruler.before('fence', '数学块', (状态, 起行, 终行, 静) => {
    const 首 = 状态.bMarks[起行] + 状态.tShift[起行];
    const 末 = 状态.eMarks[起行];
    const 本行 = 状态.src.slice(首, 末).trim();
    if (本行.slice(0, 2) !== '$$') return false;
    let 收行 = -1;
    let 内容 = '';
    if (本行.length > 4 && 本行.slice(-2) === '$$') {
      收行 = 起行;                                  // $$x$$ 一行写完
      内容 = 本行.slice(2, -2).trim();
    } else {
      let i = 起行 + 1;
      while (i < 终行) {
        const a = 状态.bMarks[i] + 状态.tShift[i];
        if (状态.src.slice(a, 状态.eMarks[i]).trim() === '$$') { 收行 = i; break; }
        i += 1;
      }
      if (收行 === -1) return false;
      内容 = 状态.getLines(起行 + 1, 收行, 状态.tShift[起行], false).trim();
    }
    if (静) return true;
    const 记 = 状态.push('math_block', 'math', 0);
    记.content = 内容;
    记.map = [起行, 收行 + 1];
    状态.line = 收行 + 1;
    return true;
  }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] });

  md.renderer.rules.math_inline = (记号们, 位) => '<span class="数学行内">' + 渲公式(记号们[位].content, false) + '</span>';
  md.renderer.rules.math_block = (记号们, 位) => '<div class="数学块">' + 渲公式(记号们[位].content, true) + '</div>';

  const 洗净 = (脏) => window.DOMPurify.sanitize(脏, { ADD_ATTR: ['target', 'rel', 'class'] });

  // 草稿里要扣掉的"协议块" —— exec 那轮模型边想边说的原文里可能夹着这些:
  //   ① 自家 `<调用>…</调用>`   ② 小米 MiMo 的 `<tool_call>…</tool_call>`
  //   ③ DeepSeek 的 DSML(全角竖线夹着 DSML)   ④ DeepSeek 官方模板那族 `<｜tool▁…｜>`
  // 它们只该待在过程面板里(2026-10-09 老板点名过"跑着时正文区露原始md")。
  // ★ 只扣**草稿**: final 来的定稿一字不动 —— 正文里真讲这些标记的场合也不少。
  // ★ 片段边界会把一个标记切成两半, 所以每次都拿"攒到现在的全量"重扣; 而且从第一处标记起
  //   **整段截断**(标记块常常跨行跨片段, 与其猜它的边界在哪, 不如让它后面的草稿等定稿)。
  const 协议头 = /<调用>|<tool_call>|[｜|]{2}DSML[｜|]{2}|<\/?dsml:|<[｜|][^｜|>\n]{1,40}[｜|]>/;
  function 去协议(文) {
    const 处 = 文.search(协议头);
    const 果 = 处 < 0 ? 文 : 文.slice(0, 处);
    return 果.replace(/<[^<>\n]{0,30}$/, '');      // 尾巴上没补齐的"<…"先扣住, 等下一个片段
  }

  // ─────────────────────────── 2. 块的抛光: 代码块/表格/外链 ───────────────────────────

  function 取齐(节点, 选择器) {
    // ★ 顶层块本身就可能命中(代码块/表格就是顶级块) —— querySelectorAll 只看后代, 会漏掉它自己
    const 出 = [];
    if (节点.matches(选择器)) 出.push(节点);
    节点.querySelectorAll(选择器).forEach((子) => 出.push(子));
    return 出;
  }

  function 抛光(块节点) {
    let 顶 = 块节点;
    取齐(顶, 'pre > code').forEach((码) => {
      const 原pre = 码.parentElement;
      if (!原pre || 原pre.dataset.抛光) return;
      原pre.dataset.抛光 = '1';
      const 语言 = (码.className.match(/language-([\w+#.-]+)/) || [])[1] || '';
      if (!/数学/.test(码.className) && window.hljs) {
        try { window.hljs.highlightElement(码); } catch (错) { /* 半截代码高亮失败不该打断渲染 */ }
      }
      const 外壳 = document.createElement('div');
      外壳.className = '代码块';
      const 头 = document.createElement('div');
      头.className = '代码头';
      const 标签 = document.createElement('span');
      标签.className = '语言';
      标签.textContent = 语言 || 'text';
      const 复制 = document.createElement('button');
      复制.type = 'button';
      复制.className = '复制按钮';
      复制.textContent = '复制';
      复制.addEventListener('click', () => {
        navigator.clipboard.writeText(码.innerText).then(() => {
          复制.textContent = '已复制';
          setTimeout(() => { 复制.textContent = '复制'; }, 1200);
        });
      });
      头.append(标签, 复制);
      原pre.replaceWith(外壳);
      外壳.append(头, 原pre);
      if (原pre === 顶) 顶 = 外壳;          // 顶层被换了壳 -> 返回新壳
    });

    取齐(顶, 'table').forEach((表) => {
      if (表.parentElement && 表.parentElement.classList.contains('表壳')) return;
      const 壳 = document.createElement('div');
      壳.className = '表壳';
      表.replaceWith(壳);
      壳.appendChild(表);
      if (表 === 顶) 顶 = 壳;
    });

    取齐(顶, 'a[href^="http"]').forEach((链) => {
      链.target = '_blank';
      链.rel = 'noopener noreferrer';
    });

    return 顶;
  }

  // ─────────────────────────── 3. 流式答案: 块级复用 ───────────────────────────

  class 流式答案 {
    constructor(根) {
      this.根 = 根;
      this.正文 = '';
      this.草稿 = '';                      // 边流边攒的原文(可能夹协议标记) —— 渲染前过 去协议()
      this.旧节点 = [];
      this.旧键 = [];
      this.排队 = false;
    }

    推(增量) {                             // 草稿路(answer 事件): 边流边渲染, 协议标记扣掉
      this.草稿 += 增量;
      this.正文 = 去协议(this.草稿);
      this.排队一次();
    }

    置(全文) {                             // 定稿路(final 事件 / 历史存档): 一字不动
      this.草稿 = 全文;
      this.正文 = 全文;
      this.排队一次();
    }

    排队一次() {
      if (this.排队) return;
      this.排队 = true;
      requestAnimationFrame(() => { this.排队 = false; this.画(); });
    }

    画() {
      const 沙盒 = document.createElement('div');
      沙盒.innerHTML = 洗净(md.render(this.正文));
      const 原始块 = Array.from(沙盒.children);
      const 新键 = 原始块.map((节点) => 节点.outerHTML);          // 抛光**之前**的原始形态当键
      const 新节点 = [];
      for (let 位 = 0; 位 < 原始块.length; 位 += 1) {
        const 旧节点 = this.旧节点[位];
        if (旧节点 && this.旧键[位] === 新键[位]) {                // ② 一个字节没变 → 留着
          新节点.push(旧节点);
          continue;
        }
        const 是新的 = 位 >= this.旧节点.length;
        const 成品 = 抛光(原始块[位]);                            // ③ 抛光的可能换了外壳
        if (是新的) 成品.classList.add('md-新');                   //    新块淡入一次
        新节点.push(成品);
      }
      this.根.replaceChildren(...新节点);
      this.旧节点 = 新节点;
      this.旧键 = 新键;
    }

    完成() {
      this.根.classList.add('md-完成');                           // ③ 动画全关
    }
  }

  // ─────────────────────────── 4. 过程面板(agent 的步骤) ───────────────────────────

  const 类名表 = {
    think: ['想', '步暗'],
    reply: ['说', ''],
    command: ['跑', '步命令'],
    output: ['输出', '步输出'],
    output_file: ['全文', '步暗'],
    stage: ['阶段', '步阶段'],
    note: ['系统', '步阶段'],
    declaration: ['声明', '步声明'],
    tick: ['读秒', '步读秒'],
    error: ['出错', '步错']
  };

  class 过程面板 {
    constructor(挂到) {
      this.详情 = document.createElement('details');
      this.详情.className = '过程';
      this.总 = document.createElement('summary');
      this.正文 = document.createElement('div');
      this.正文.className = '过程体';
      this.详情.append(this.总, this.正文);
      this.步数 = 0;
      this.末类 = '';
      this.末元素 = null;
      this.排队 = false;
      挂到.appendChild(this.详情);
      this.刷新总();
    }

    刷新总() {
      this.总.textContent = this.忙着 ? '过程 · 进行中…' : `过程 · ${this.步数} 步`;
    }

    收(类, 文本) {
      if (类 === 'think' || 类 === 'reply') {
        if (this.末类 !== 类 || !this.末元素) this.新步(类, '');
        this.末元素.textContent += 文本;
        return;
      }
      if (类 === 'tick') {
        // ★ 定时读秒: **同一格原地改写** —— 逐秒新起一格的话, 等三小时就是上万格,
        //   面板和落盘的过程存档都得灌爆(存档只留「开始等 / 等到了」两条)。
        if (this.末类 !== 'tick' || !this.末元素) this.新步('tick', 文本);
        else this.末元素.textContent = 文本;
        return;
      }
      this.新步(类, 文本);
    }

    新步(类, 文本) {
      const [名, 样式] = 类名表[类] || ['系统', ''];
      const 步 = document.createElement('div');
      步.className = '步 ' + 样式;
      const 头 = document.createElement('span');
      头.className = '步名';
      头.textContent = 名;
      const 体 = document.createElement('span');
      体.className = '步文';
      体.textContent = 文本;
      步.append(头, 体);
      this.正文.appendChild(步);
      this.步数 += 1;
      this.末类 = 类;
      this.末元素 = 体;
      this.刷新总();
      return 步;
    }
  }

  // ─────────────────────────── 5. 滚动与界面细节 ───────────────────────────

  function 贴底() {
    return document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) < 90;
  }
  // ★ 刷新/重开一定要落在最新那轮上: 浏览器默认"恢复上次的滚动位置", 先关掉它(2026-10-10)
  try { history.scrollRestoration = 'manual'; } catch (e) { /* 老浏览器没有就算了 */ }
  let 定在底 = true;                       // 用户没自己动手之前, 内容长高就一直跟到最新
  ['wheel', 'touchstart', 'keydown', 'mousedown'].forEach((名) => {
    window.addEventListener(名, () => { 定在底 = false; }, { passive: true });
  });
  function 落到底() {
    定在底 = true;
    window.scrollTo({ top: document.documentElement.scrollHeight });
  }
  function 回到底() {
    落到底();
  }
  window.addEventListener('scroll', () => { 到底.hidden = 贴底(); }, { passive: true });
  到底.addEventListener('click', 回到底);
  // 图块/公式/字体陆续进来会把页面顶高 —— 只要用户还没动手, 就一直贴着底
  new ResizeObserver(() => { if (定在底) window.scrollTo({ top: document.documentElement.scrollHeight }); }).observe(流);

  问框.addEventListener('input', () => {
    问框.style.height = 'auto';
    问框.style.height = Math.min(问框.scrollHeight, 220) + 'px';
  });
  问框.addEventListener('keydown', (事) => {
    if (事.key === 'Enter' && !事.shiftKey && !事.isComposing) {
      事.preventDefault();
      问表.requestSubmit();
    }
  });

  // ─────────────────── 拖进来就填路径 ───────────────────
  // 老板 2026-10-11 要的: 文件 / 文件夹拖到窗口上 → 输入栏自动写入带引号的路径,
  // 并且有颜色反馈(拖着亮、松手闪、状态行报一句), 让人知道"功能是好的、真填进去了"。
  // ★ 浏览器出于安全不给拖进来的 File 真实路径, 但**从文件管理器拖**会带 text/uri-list
  //   (file:///home/lou/…), 终端/编辑器给 text/plain, Electron 下还有 file.path —— 三条都试。
  // ★ 只吃"像路径"的: 拖一段普通文字进来时原样交回浏览器默认, 不硬塞成路径还添俩引号。
  let 拖动层数 = 0;                     // dragenter/dragleave 在子元素间来回跳, 计数才不乱闪

  function 像路径(文) {
    return /^(~?\/|[A-Za-z]:[\\/]|file:\/\/|\\\\)/.test(文.trim());
  }
  function 去引号(文) {
    const 净 = 文.trim();
    const 配 = { '"': '"', "'": "'", '“': '”', '‘': '’', '「': '」', '『': '』' };
    if (净.length > 1 && 配[净[0]] === 净[净.length - 1]) return 净.slice(1, -1);
    return 净;
  }
  function uri转路径(段) {
    let 文 = 段.trim();
    if (!文 || 文.startsWith('#')) return '';        // uri-list 里 # 开头是注释行
    if (文.startsWith('file://')) {
      文 = 文.slice(7);                              // file:///home/x -> /home/x
      if (文.startsWith('localhost/')) 文 = 文.slice(9);
    }
    try { 文 = decodeURIComponent(文); } catch (_) { /* 不是 %XX 编码就原样 */ }
    return 文;
  }
  function 读拖拽数据(事) {
    const 数据 = 事.dataTransfer, 出 = [];
    for (const 行 of String(数据.getData('text/uri-list') || '').split(/\r?\n/)) {
      const 路 = uri转路径(行);
      if (路) 出.push(路);
    }
    if (!出.length) {
      for (const 行 of String(数据.getData('text/plain') || '').split(/\r?\n/)) {
        const 净 = 去引号(行);
        if (净) 出.push(净);
      }
    }
    if (!出.length) {                                // 兜底: Electron 有 file.path, 浏览器只有名字
      for (const 档 of Array.from(数据.files || [])) 出.push(档.path || 档.name);
    }
    return 出;
  }
  function 能拖进来(事) {
    const 类 = 事.dataTransfer ? Array.from(事.dataTransfer.types || []) : [];
    return 类.includes('Files') || 类.includes('text/uri-list') || 类.includes('text/plain');
  }
  function 报一句(文, 坏) {
    const 旧文 = 状态行.textContent, 旧色 = 状态行.style.color;
    状态行.textContent = 文;
    状态行.style.color = 坏 ? 'var(--warn)' : 'var(--ok)';
    setTimeout(() => { 状态行.textContent = 旧文; 状态行.style.color = 旧色; }, 4000);
  }

  function 重置拖动() {
    拖动层数 = 0;
    document.body.classList.remove('拖入中');
  }

  window.addEventListener('dragenter', (事) => {
    if (!能拖进来(事)) return;
    事.preventDefault();
    拖动层数 += 1;
    document.body.classList.add('拖入中');
  });
  window.addEventListener('dragover', (事) => {
    if (!能拖进来(事)) return;
    事.preventDefault();                             // 不拦这一下, 后面根本收不到 drop
    事.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('dragleave', () => {
    拖动层数 = Math.max(0, 拖动层数 - 1);
    if (!拖动层数) document.body.classList.remove('拖入中');
  });
  window.addEventListener('drop', (事) => {
    if (!能拖进来(事)) return;
    const 原始 = 读拖拽数据(事);
    const 路径们 = 原始.filter(像路径);
    // ★ 只要这一拖带着"文件 / uri-list", 无论能不能解出路径, **一律吃掉** ——
    //   不然浏览器按"拖了个文件/链接进来"处理, 直接把页面导航走, 会话就丢了。
    //   (这是 2026-10-11 在 CDP 上真撞出来的: 一次没吃下的 drop 把页面顶成了 about:blank#blocked)
    const 带文件 = Array.from(事.dataTransfer.types || [])
      .some((型) => 型 === 'Files' || 型 === 'text/uri-list');
    if (!路径们.length) {
      重置拖动();
      if (!带文件) return;                            // 纯文字: 交回浏览器默认(能往输入框里落字)
      事.preventDefault();
      const 有网址 = 原始.some((文) => /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(文)
        && !文.startsWith('file://'));
      报一句(!原始.length ? '已接收拖入内容，但无法解析路径 —— 请改从文件管理器窗口拖入'
        : 有网址 ? '拖进来的不是本地路径（看着像网址/链接）'
          : '仅取到文件名，未取到完整路径 —— 需从文件管理器窗口拖入', true);
      return;
    }
    事.preventDefault();
    重置拖动();
    填进输入框(路径们);
  });

  // ─────────────────── 导入按钮: 本机目录点选 ───────────────────
  // 老板 2026-10-11 追加要的("在对话框上再放一个导入文件按钮")。
  // ★ 浏览器出于安全不给 <input type=file> 的真实路径 —— 但我们服务就在本机, 让**服务**列目录,
  //   页面里点文件夹进去、点文件/「选当前这层」就把绝对路径填进输入框(和拖拽同一个落点)。
  const 导入钮 = document.getElementById('导入钮');
  const 路径罩 = document.getElementById('路径罩');
  const 路径框 = document.querySelector('.路径框');
  const 路径单 = document.getElementById('路径单');
  const 路径条 = document.getElementById('路径条');
  const 路径灰 = document.getElementById('路径灰');
  let 当前目录 = localStorage.getItem('路径上次') || '';
  let 行号 = -1;                       // 键盘走位停在第几行, -1 = 还没动过键盘(用鼠标就不显示)

  function 关路径() {
    路径罩.hidden = true;
    问框.focus();
  }

  // 键盘走位: ↑↓ 换行, Enter 进目录/选文件, Backspace 回上一级 —— 和文件管理器一个习惯,
  // 不用把鼠标挪到某个小条目上。走位的那行挂 .亮(左侧绿条), 和左边栏「选中的节」同一个语言。
  function 行们() {
    return Array.from(路径单.querySelectorAll('.路径行'));
  }

  function 画高亮() {
    const 排 = 行们();
    排.forEach((行, 号) => 行.classList.toggle('亮', 号 === 行号));
    if (排[行号]) 排[行号].scrollIntoView({ block: 'nearest' });
  }

  function 动高亮(步) {
    const 排 = 行们();
    if (!排.length) return;
    行号 = 行号 < 0 ? (步 > 0 ? 0 : 排.length - 1) : 行号 + 步;
    行号 = Math.max(0, Math.min(排.length - 1, 行号));
    画高亮();
  }

  function 跳到行(号) {
    const 排 = 行们();
    if (排.length) { 行号 = Math.max(0, Math.min(排.length - 1, 号)); 画高亮(); }
  }

  function 按高亮行() {
    const 排 = 行们();
    const 行 = 排[行号] || 排[0];
    if (行) 行.click();
  }

  function 回上一级() {
    // ★ 别拿 textContent 找父行: 每行前面还挂着个「▸」图标符, 拼起来是 "▸..（上一级）",
    //   startsWith('..') 永远匹配不上(踩过)。父行在铺项时挂了 .上级 标记, 认标记最稳。
    const 行 = 路径单.querySelector('.路径行.上级');
    if (行) 行.click();
  }

  function 填进输入框(路径们) {
    const 段 = 路径们.map((路) => '"' + 路 + '"').join(' ');
    const 旧 = 问框.value;
    问框.value = 旧 && !/\s$/.test(旧) ? 旧 + ' ' + 段 : 旧 + 段;
    问框.dispatchEvent(new Event('input'));           // 让高度自适应那条逻辑跑一遍
    问框.focus();
    问框.setSelectionRange(问框.value.length, 问框.value.length);
    问表.classList.add('刚填入');
    setTimeout(() => 问表.classList.remove('刚填入'), 800);
    报一句('已填入 ' + 路径们.length + ' 个路径：'
      + 路径们.map((路) => 路.split('/').pop()).join('、'));
  }

  async function 开路径(目录) {
    路径罩.hidden = false;
    路径框.focus();                   // 焦点先收进弹窗(否则 Tab 第一步就跑到背景的输入框上)
    路径灰.textContent = '读取中…';
    路径单.textContent = '';
    let 响应;
    try {
      响应 = await fetch('/api/路径?目录=' + encodeURIComponent(目录 || 当前目录 || ''));
    } catch (错) {
      路径灰.textContent = '无法连接服务：' + 错;
      return;
    }
    if (!响应.ok) {
      // ★ 老板 13:0x 就撞过这个: 页面是新代码、web 进程还是老代码, 接口压根不在 -> 面板一片空白。
      //   服务端改动**必须重启进程**才生效(静态页 F5 不够), 所以这里把话说清楚, 别让人对着空面板猜。
      路径灰.textContent = 响应.status === 404
        ? '当前 web 进程未加载该接口（服务启动早于本次改动）—— 重启 web 服务后可用。'
        : '服务返回 HTTP ' + 响应.status;
      return;
    }
    let 果;
    try {
      果 = await 响应.json();
    } catch (错) {
      路径灰.textContent = '响应非 JSON：' + 错;
      return;
    }
    if (!果.好) {
      路径灰.textContent = 果.说明 || '无法列出';
      return;
    }
    当前目录 = 果.目录;
    try { localStorage.setItem('路径上次', 当前目录); } catch (_) { /* 无痕模式就算了 */ }
    路径条.textContent = 当前目录;
    路径条.title = 当前目录;
    铺项(果);
  }

  function 铺项(果) {
    路径单.textContent = '';
    行号 = -1;                       // 换了一层目录, 键盘走位从这层重新开始
    const 加行 = (显示名, 是目录, 淡, 点它, 标) => {
      const 行 = document.createElement('button');
      行.type = 'button';
      行.className = '路径行' + (是目录 ? ' 是目录' : '') + (淡 ? ' 淡' : '') + (标 ? ' ' + 标 : '');
      const 号 = document.createElement('span');
      号.className = '路径号';
      号.textContent = 是目录 ? '▸' : '·';
      const 名 = document.createElement('span');
      名.className = '路径名';
      名.textContent = 显示名;
      行.append(号, 名);
      行.addEventListener('click', 点它);
      路径单.appendChild(行);
    };
    if (果.上级) 加行('..（上一级）', true, true, () => 开路径(果.上级), '上级');
    果.项.forEach((项) => 加行(项.名 + (项.是目录 ? '/' : ''), 项.是目录, 项.隐, () => {
      const 全 = 当前目录.replace(/\/+$/, '') + '/' + 项.名;
      if (项.是目录) {
        开路径(全);
      } else {
        填进输入框([全]);
        关路径();
      }
    }));
    if (!果.项.length) 路径灰.textContent = 果.说明 || '此层为空';
    else 路径灰.textContent = 果.项.length + '  项 · 点击文件夹进入、点击文件填入 · 键盘 ↑↓ + Enter'
      + (果.说明 ? ' · ' + 果.说明 : '');
  }

  导入钮.addEventListener('click', () => 开路径(''));
  document.getElementById('路径关').addEventListener('click', 关路径);
  document.getElementById('路径消').addEventListener('click', 关路径);
  document.getElementById('选这层').addEventListener('click', () => {
    if (当前目录) 填进输入框([当前目录]);
    关路径();
  });
  路径罩.addEventListener('click', (事) => { if (事.target === 路径罩) 关路径(); });
  document.addEventListener('keydown', (事) => {
    if (事.key === 'Escape' && !路径罩.hidden) 关路径();
    if ((事.ctrlKey || 事.metaKey) && 事.key.toLowerCase() === 'o') {
      事.preventDefault();
      开路径('');
    }
    if (路径罩.hidden) return;                       // 下面这些只在面板开着时管
    // 面板盖着整屏, 这时的方向键/Enter/退格只可能是在面板里挑东西, 不会和输入框打架。
    if (事.key === 'ArrowDown') { 事.preventDefault(); 动高亮(1); return; }
    if (事.key === 'ArrowUp') { 事.preventDefault(); 动高亮(-1); return; }
    if (事.key === 'PageDown') { 事.preventDefault(); 动高亮(10); return; }
    if (事.key === 'PageUp') { 事.preventDefault(); 动高亮(-10); return; }
    if (事.key === 'Home') { 事.preventDefault(); 跳到行(0); return; }
    if (事.key === 'End') { 事.preventDefault(); 跳到行(行们().length - 1); return; }
    if (事.key === 'Backspace') { 事.preventDefault(); 回上一级(); return; }
    if (事.key === 'Enter') { 事.preventDefault(); 按高亮行(); return; }
    // Tab 别跑出弹窗: 面板是模态的, 让焦点在面板内部转圈(不然 Tab 两三下就摸到背景的输入框/发送)
    if (事.key === 'Tab') {
      事.preventDefault();
      const 可点 = Array.from(路径框.querySelectorAll('button'))
        .filter((钮) => 钮.offsetParent !== null);
      if (!可点.length) return;
      const 站在 = 可点.indexOf(document.activeElement);
      const 往 = 事.shiftKey ? -1 : 1;
      const 下 = 站在 < 0 ? (往 > 0 ? 0 : 可点.length - 1)
        : (站在 + 往 + 可点.length) % 可点.length;
      可点[下].focus();
    }
  });


  空态.querySelectorAll('.示例 button').forEach((钮) => {
    钮.addEventListener('click', () => { 问框.value = 钮.dataset.问 || ''; 问表.requestSubmit(); });
  });

  function 铺状态(状态) {
    const 服务 = 状态.服务 || {};
    服务灯.className = '点 ' + (服务.通 ? '亮' : '灭');
    模型名.textContent = 服务.模型 || '未配置模型';
    模型名.title = 服务.说明 || '';
    if (!服务.通) 状态行.textContent = '模型端点不可达：' + (服务.说明 || '看 .env');
  }

  // ─────────────────── 6. 历史记录: 全量摆开 + 跳点 + 懒加载 ───────────────────

  let 目录 = [];          // 侧栏那份跳点表(全量: 只有问题/时间/用时)
  let 总 = 0;             // 盘上一共几轮
  let 已载 = 0;           // 已从盘上取回几轮(最新往回数) —— 这是"取到哪了", 不是"挂着几轮"
  let 还有更早 = false;
  let 取着 = false;

  // ── 懒加载 + 动态卸载(2026-10-10) ──
  //   一次取 一批=10 轮; DOM 里同时最多挂 上限=30 轮 —— 离视口远的轮只留个"壳":
  //   子节点全掏空、高度锁住(滚动几何不变、视口不跳), 数据留在 数据 里, 滚回去再补上。
  //   省掉的正是几十轮正文那堆 md 渲染 + 高亮 + 公式的节点。
  const 一批 = 10;
  const 上限 = 30;
  const 数据 = new Map();   // 序号 → 条(取回来的都在, 摘了 DOM 也不丢)
  const 挂 = new Set();     // 当前真挂着内容的那些序号

  function 轮盒(序) { return 流.querySelector(`.轮[data-序号="${序}"]`); }

  function 挂一轮(序) {
    const 条 = 数据.get(序);
    if (!条 || 挂.has(序)) return;
    const 新轮 = 造一轮(条, 注脚(条));
    新轮.dataset.序号 = String(序);
    const 旧壳 = 轮盒(序);
    if (旧壳) {
      流.replaceChild(新轮, 旧壳);                    // 最常见的路: 壳 → 内容
    } else {                                          // 没壳: 按序号插到该在的位置
      let 后 = null;
      for (const 号 of 挂) if (号 > 序 && (后 === null || 号 < 后)) 后 = 号;
      if (后 === null) 流.appendChild(新轮);
      else 流.insertBefore(新轮, 轮盒(后));
    }
    挂.add(序);
  }

  // 掏空一个轮: 子节点全扔、高度锁住; 内容还在 数据 里, 滚回去再挂
  function 摘一轮(序) {
    const el = 轮盒(序);
    if (!el || !挂.has(序)) return;
    el.style.height = el.getBoundingClientRect().height + 'px';
    el.textContent = '';
    el.classList.add('壳');
    挂.delete(序);
  }

  // 视口附近的挂上、离得远的摘掉 —— 滚动时约一帧一次
  let 平衡约着 = false;
  function 平衡() {
    if (平衡约着) return;
    平衡约着 = true;
    requestAnimationFrame(() => {
      平衡约着 = false;
      const 高 = window.innerHeight;
      const 远 = [];
      for (const el of 流.querySelectorAll('.轮[data-序号]')) {
        const 号 = Number(el.dataset.序号);
        const 盒 = el.getBoundingClientRect();
        const 在附近 = 盒.bottom > -高 * 1.5 && 盒.top < 高 * 2.5;   // 视口上下各留一屏多的余量
        if (在附近) {
          if (!挂.has(号) && 数据.has(号)) 挂一轮(号);
        } else if (挂.has(号)) {
          远.push({ 号, 距: 盒.bottom < 0 ? -盒.bottom : 盒.top });
        }
      }
      远.sort((甲, 乙) => 乙.距 - 甲.距);                  // 离得最远的先摘
      for (const 件 of 远) {
        if (挂.size <= 上限) break;
        摘一轮(件.号);
      }
      if (还有更早 && !取着 && window.scrollY < 400) 载更早();
    });
  }
  window.addEventListener('scroll', 平衡, { passive: true });

  function 高亮(序) {
    侧历史.querySelectorAll('.史项').forEach((钮) => {
      钮.classList.toggle('当前', Number(钮.dataset.序) === 序);
    });
  }

  function 铺目录(数) {
    总 = 数.总 || 0;
    目录 = 数.目录 || [];
    侧历史.textContent = '';
    if (!目录.length) {
      const 空 = document.createElement('div');
      空.className = '史空';
      空.textContent = '暂无记录';
      侧历史.appendChild(空);
      return;
    }
    [...目录].reverse().forEach((条) => {
      const 钮 = document.createElement('button');
      钮.type = 'button';
      钮.className = '史项';
      钮.dataset.序 = String(条.序号);
      钮.title = (条.问 || '').replace(/\s+/g, ' ');
      const 头 = document.createElement('span');
      头.textContent = 钮.title.slice(0, 42) || '（问题为空）';
      const 时 = document.createElement('span');
      时.className = '史时';
      时.textContent = `${(条.时间 || '').slice(5)} · ${条.用时 ?? '?'}s`;
      钮.append(头, 时);
      钮.addEventListener('click', () => 跳过去(条.序号));
      侧历史.appendChild(钮);
    });
  }

  function 拉目录() {
    return fetch('/api/历史').then((响) => 响.json()).then(铺目录).catch(() => {});
  }

  function 注脚(条) {
    return `${条.时间 || ''} · 用时 ${条.用时 ?? '?'} 秒`;
  }

  // 一轮的静态形态: 问 + 过程(存档里那份) + 答案(md 渲染好) —— 历史轮走这里, 和现场那轮长得一样
  function 造一轮(条, 注) {
    const 轮 = document.createElement('section');
    轮.className = '轮';
    if (条.序号 !== undefined) 轮.dataset.序号 = String(条.序号);
    const 问块 = document.createElement('div');
    问块.className = '问';
    问块.textContent = 条.问 || '';
    const 过程位 = document.createElement('div');
    过程位.className = '过程位';
    const 答案块 = document.createElement('div');
    答案块.className = '答案 md';
    轮.append(问块, 过程位, 答案块);
    // ★ 过程随轮入库, 页面关掉再开还在(2026-10-09 补): 存档里那串步骤照原样铺回面板。
    //   默认折起来 —— 历史一打开就是几十轮, 全摊开没法看(现场那轮收尾时也是折的)。
    const 步们 = Array.isArray(条.过程) ? 条.过程 : [];
    if (步们.length) {
      const 过程 = new 过程面板(过程位);
      步们.forEach((步) => 过程.收(String(步.kind || ''), String(步.text || '')));
      过程.详情.open = false;
    }
    const 答案 = new 流式答案(答案块);
    答案.置(条.答 || '（这轮没有正文）');
    答案.完成();
    if (注) {
      const 尾 = document.createElement('div');
      尾.className = '灰 小字';
      尾.textContent = 注;
      轮.appendChild(尾);
    }
    return 轮;
  }

  async function 取一段(起, 数) {
    try {
      return await fetch(`/api/历史/段?起=${起}&数=${数}`).then((响) => 响.json());
    } catch (错) {
      return null;
    }
  }

  async function 载更早(数 = 一批) {
    if (取着 || !还有更早) return false;
    取着 = true;
    哨兵.textContent = '正在加载更早记录…';
    const 旧高 = document.documentElement.scrollHeight;
    const 回 = await 取一段(已载, 数);
    if (回 && (回.段 || []).length) {
      回.段.forEach((条) => 数据.set(Number(条.序号), 条));
      已载 += 回.段.length;
      还有更早 = !!回.还有更早的;
      // 这批序号都比现在挂着的那些小, 挂一轮 自己会插到最前面(结果还是 旧 → 新)
      回.段.forEach((条) => 挂一轮(Number(条.序号)));
      // 顶上多出一截, 把可视位置顶回去 —— 不然读到一半会被弹走(贴着底时不用管)
      if (!定在底) window.scrollBy(0, document.documentElement.scrollHeight - 旧高);
      平衡();                                   // 远的那头该摘就摘
    } else {
      还有更早 = false;
    }
    哨兵.textContent = 还有更早 ? '上拉加载更早记录' : '';
    取着 = false;
    return true;
  }

  async function 跳过去(序) {
    if (在看设置) 切页('对话');
    定在底 = false;                 // ★ 主动离开"最新": 显式解除贴底, 否则跟随会把跳转顶回去
    let 兜 = 0;
    // 目标还没摆出来就先往回取(它是第几轮、离最新多远, 一目了然)
    while (还有更早 && (总 - 1 - 序) >= 已载 && 兜 < 40) {
      兜 += 1;
      if (!(await 载更早())) break;
    }
    高亮(序);
    if (数据.has(序)) 挂一轮(序);               // 取回来了但被卸载了 → 先补上内容再跳
    const 轮 = 流.querySelector(`.轮[data-序号="${序}"]`);
    const 那条 = 目录.find((件) => 件.序号 === 序);
    if (那条) {                                  // 顶栏跟着显示"在看哪一轮"
      当前名 = (那条.问 || '').replace(/\s+/g, ' ').slice(0, 46) || '对话';
      页眉.textContent = 当前名;
      页眉.title = 那条.问 || '';
    }
    if (!轮) {
      状态行.textContent = `第 ${序 + 1} 轮没在正文里（那轮没存下内容）`;
      return;
    }
    轮.scrollIntoView({ block: 'center' });
    轮.classList.add('跳着');
    setTimeout(() => 轮.classList.remove('跳着'), 1500);
    状态行.textContent = `跳到 ${(那条 && 那条.问 ? 那条.问 : '第 ' + (序 + 1) + ' 轮').slice(0, 28)}`;
  }

  // 哨兵一进视野 = 往上翻到头了 → 接着取更早的一批
  const 观察 = new IntersectionObserver((条们) => {
    if (条们.some((条) => 条.isIntersecting) && 还有更早 && !取着) 载更早();
  }, { rootMargin: '160px' });
  观察.observe(哨兵);

  // ─────────────────── 7. 设置页: 接口 / 开关 / 现状 ───────────────────

  function 设节(题, 注) {
    const 节 = document.createElement('div');
    节.className = '设节';
    const 头 = document.createElement('div');
    头.className = '设节题';
    头.textContent = 题;
    节.appendChild(头);
    if (注) {
      const 注行 = document.createElement('div');
      注行.className = '设节注';
      注行.textContent = 注;
      节.appendChild(注行);
    }
    return 节;
  }

  function 设框(值, 占位, 类) {
    const 框 = document.createElement('input');
    框.type = 'text';
    框.className = '设框 ' + (类 || '');
    框.value = 值 || '';
    框.placeholder = 占位 || '';
    return 框;
  }

  function 设行(键, 值, 色) {
    const 行 = document.createElement('div');
    行.className = '设行';
    const 左 = document.createElement('span');
    左.className = '设键';
    左.textContent = 键;
    const 右 = document.createElement('span');
    右.className = '设值' + (色 ? ' ' + 色 : '');
    右.textContent = 值;
    行.append(左, 右);
    return 行;
  }

  function 铺接口(数) {
    const 节 = 设节(
      '接口（三支 agent + 向量模型）',
      '填了就写进 .env（改前自动备份到 state/env-backup/）。整组留空 = 继承主线配置；密钥留空 = 不动它。'
    );
    const 表 = document.createElement('div');
    表.className = '设表';
    const 头行 = document.createElement('div');
    头行.className = '设表行 头行';
    ['哪一支', '端点', '模型', '密钥'].forEach((字) => {
      const 格 = document.createElement('span');
      格.textContent = 字;
      头行.appendChild(格);
    });
    表.appendChild(头行);
    (数.接口 || []).forEach((组) => {
      const 行 = document.createElement('div');
      行.className = '设表行';
      行.dataset.组 = 组.名;
      行.dataset.原端点 = 组.端点 || '';      // 存一份原值: 保存时只递交真改过的那些
      行.dataset.原模型 = 组.模型 || '';
      const 左 = document.createElement('div');
      左.className = '设支';
      const 名 = document.createElement('span');
      名.className = '设支名';
      名.textContent = 组.名;
      名.style.display = 'block';
      if (!组.在用 && 组.名 !== '主线') {
        const 跟 = document.createElement('span');
        跟.className = '跟';
        跟.textContent = '继承主线配置';
        名.appendChild(跟);
      }
      左.appendChild(名);
      if (组.说明) {
        const 注 = document.createElement('span');
        注.className = '设支注';
        注.textContent = 组.说明;
        左.appendChild(注);
      }
      行.append(
        左,
        设框(组.端点, 组.名 === '主线' ? '必填' : '空 = 继承主线', '端点'),
        设框(组.模型, 组.名 === '主线' ? '必填' : '空 = 继承主线', '模型'),
        设框('', 组.密钥 ? `已设 ${组.密钥}（留空不改）` : '未设置', '密钥')
      );
      表.appendChild(行);
    });
    节.appendChild(表);
    return 节;
  }

  function 铺开关(数) {
    const 节 = 设节('开关', '各开关写入其对应配置文件；每轮运行时重新读取，下一问即按新值执行，无需重启。');
    (数.开关 || []).forEach((件) => {
      const 行 = document.createElement('label');
      行.className = '开关行';
      行.dataset.名 = 件.名;
      行.dataset.原值 = 件.值 === true ? '1' : '0';
      const 文 = document.createElement('span');
      文.className = '开关文';
      const 名 = document.createElement('span');
      名.className = '开关名';
      名.textContent = 件.名;
      const 注 = document.createElement('span');
      注.className = '开关注';
      注.textContent = `${件.说明 || ''}　·　写进 ${件.落点}`;
      文.append(名, 注);
      const 闸 = document.createElement('input');
      闸.type = 'checkbox';
      闸.checked = 件.值 === true;
      const 字样 = document.createElement('span');
      字样.className = '开关字';
      字样.textContent = 闸.checked ? '开' : '关';
      闸.addEventListener('change', () => { 字样.textContent = 闸.checked ? '开' : '关'; 记改动(); });
      行.append(文, 字样, 闸);
      节.appendChild(行);
    });
    return 节;
  }

  // ─────────────────── 设置页·数据库（表格化 + 手动搜索）───────────────────
  // 两条路都打到 /api/库*，后端 bridge 只做搬运 —— web 与命令行看的是同一张表。
  function 铺数据库() {
    const 节 = 设节(
      '数据库',
      '三层共用一张表（历史对话 / 热层 / 经验层）。表格为字面过滤，搜索走语义检索（嵌入模型匹配语义相近内容）；语义检索不可用时后端自动降级为字面匹配，实际所用路径标注在结果顶部。'
    );
    const 状 = { 层: '1', 偏: 0, 每页: 20, 词: '', 来源: '' };
    const 层名 = { 1: '历史对话', 2: '热层', 3: '经验层' };

    const 概 = document.createElement('div');
    概.className = '库概';
    概.textContent = '正在读库…';
    节.appendChild(概);

    const 做层选 = () => {
      const s = document.createElement('select');
      s.className = '库选';
      [['1', '历史对话'], ['2', '热层'], ['3', '经验层']].forEach(([v, t]) => {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = t;
        s.appendChild(o);
      });
      return s;
    };

    // ── 表格那半 ──
    const 栏 = document.createElement('div');
    栏.className = '库栏';
    const 层选 = 做层选();
    const 词框 = document.createElement('input');
    词框.className = '库框';
    词框.type = 'search';
    词框.placeholder = '表内字面匹配（可留空）';
    const 源框 = document.createElement('input');
    源框.className = '库框';
    源框.type = 'text';
    源框.placeholder = '来源(可留空)';
    const 刷 = document.createElement('button');
    刷.type = 'button';
    刷.className = '库刷';
    刷.textContent = '刷新';
    栏.append(层选, 词框, 源框, 刷);
    节.appendChild(栏);

    const 表包 = document.createElement('div');
    表包.className = '库表包';
    节.appendChild(表包);
    const 页条 = document.createElement('div');
    页条.className = '库页';
    节.appendChild(页条);

    // ── 搜索那半 ──
    const 搜题 = document.createElement('div');
    搜题.className = '库搜题';
    搜题.textContent = '手动检索（语义检索为主，字面匹配兜底）';
    const 搜栏 = document.createElement('div');
    搜栏.className = '库栏';
    const 搜框 = document.createElement('input');
    搜框.className = '库框 宽';
    搜框.type = 'search';
    搜框.placeholder = '输入一句话执行检索 —— 走语义检索，非字面匹配';
    const 搜层 = 做层选();
    const 搜钮 = document.createElement('button');
    搜钮.type = 'button';
    搜钮.className = '库刷';
    搜钮.textContent = '搜';
    搜栏.append(搜框, 搜层, 搜钮);
    const 搜果 = document.createElement('div');
    搜果.className = '库果';
    搜果.textContent = '输入一句话后点击「搜」。';
    节.append(搜题, 搜栏, 搜果);

    async function 读概览() {
      try {
        const d = await (await fetch('/api/库')).json();
        if (d.说明) {
          概.textContent = '读库失败：' + d.说明;
          概.classList.add('坏');
          return;
        }
        概.classList.remove('坏');
        const 每层 = d.每层 || {};
        const 段 = Object.keys(每层).sort().map((k) => `${层名[k] || ('第' + k + '层')} ${每层[k]}`);
        概.textContent = `共 ${d.共 || 0} 条 —— ${段.join('　/　')}；来源 ${(d.来源 || []).length} 个`;
      } catch (e) {
        概.textContent = '读库失败：' + e;
        概.classList.add('坏');
      }
    }

    async function 读一页() {
      表包.textContent = '正在读…';
      const 参 = new URLSearchParams({
        层: 状.层, 偏移: String(状.偏), 每页: String(状.每页), 词: 状.词, 来源: 状.来源,
      });
      let d;
      try {
        d = await (await fetch('/api/库/翻?' + 参.toString())).json();
      } catch (e) {
        表包.textContent = '读库失败：' + e;
        return;
      }
      if (d.说明) {
        表包.textContent = '读库失败：' + d.说明;
        return;
      }
      表包.textContent = '';
      const 表 = document.createElement('table');
      表.className = '库表';
      const 头 = document.createElement('thead');
      const 头行 = document.createElement('tr');
      ['id', '层', '序', '来源', '类型', '正文', '时间 ↓'].forEach((t) => {
        const th = document.createElement('th');
        th.textContent = t;
        if (t.indexOf('时间') === 0) {
          th.title = '新的在最上面(时间倒序)。时间的取法: 自己有对话时间就用它; 经验层没有, '
            + '顺它的出处回历史对话层取那次对话的时间; 两样都没有才显示落库时间。';
        }
        头行.appendChild(th);
      });
      头.appendChild(头行);
      表.appendChild(头);
      const 身 = document.createElement('tbody');
      (d.行 || []).forEach((r) => {
        const tr = document.createElement('tr');
        const 格 = (文, 类) => {
          const td = document.createElement('td');
          if (类) td.className = 类;
          td.textContent = 文;
          return td;
        };
        // ★ 时间列(2026-10-10 修): 显示后端算好的 时间(取法: 对话时间 → 出处对话时间 → 落库时间),
        //   来路标在悬停提示里 —— 经验层的时间是顺出处回原文取的, 不标容易被看成"整层同一个时间"。
        const 时格 = 格(String(r.时间 || r.对话时间 || r.落库时间 || ''), '时');
        if (r.时间来源) {
          时格.title = '时间 ' + (r.时间 || '') + ' —— 取自' + r.时间来源
            + '(对话=这条自己的对话时间; 源对话=顺出处回历史对话层取到的; 落库=这一层被写进库的时刻)';
        }
        tr.append(
          格(String(r.id), '数'),
          格(String(r.tier), '数'),
          格(String(r.idx), '数'),
          格(String(r.source || '').split('/').pop(), '源'),
          格(r.kind || '', '类'),
          格(String(r.text || '').replace(/\s+/g, ' ').slice(0, 140), '文'),
          时格
        );
        if (r.text) tr.title = String(r.text).slice(0, 800);
        身.appendChild(tr);
      });
      表.appendChild(身);
      表包.appendChild(表);

      const 总页 = Math.max(1, Math.ceil((d.共 || 0) / 状.每页));
      const 当页 = Math.floor(状.偏 / 状.每页) + 1;
      页条.textContent = '';

      // 页码按钮(整组靠左): 首尾页 + 当前页前后各 2 页, 中间断开处用 … 顶替
      const 钮组 = document.createElement('div');
      钮组.className = '库页钮组';
      const 造钮 = (文, 目标页, 是当页 = false, 禁 = false) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = '库页钮' + (是当页 ? ' 当' : '');
        b.textContent = 文;
        b.disabled = 禁;
        if (!是当页 && !禁) {
          b.addEventListener('click', () => {
            状.偏 = (目标页 - 1) * 状.每页;
            读一页();
          });
        }
        return b;
      };
      const 窗 = 2;
      const 要 = new Set([1, 总页]);
      for (let p = 当页 - 窗; p <= 当页 + 窗; p += 1) {
        if (p >= 1 && p <= 总页) 要.add(p);
      }
      const 序 = [...要].sort((a, b) => a - b);
      钮组.appendChild(造钮('‹', 当页 - 1, false, 当页 <= 1));
      let 上一页号 = 0;
      序.forEach((p) => {
        if (上一页号 && p - 上一页号 > 1) {
          const 省 = document.createElement('span');
          省.className = '库页省';
          省.textContent = '…';
          钮组.appendChild(省);
        }
        钮组.appendChild(造钮(String(p), p, p === 当页));
        上一页号 = p;
      });
      钮组.appendChild(造钮('›', 当页 + 1, false, 当页 >= 总页));
      const 讯 = document.createElement('span');
      讯.className = '库页讯';
      讯.textContent = `第 ${当页} / ${总页} 页　·　共 ${d.共 || 0} 条`;
      页条.append(钮组, 讯);
    }

    层选.addEventListener('change', () => {
      状.层 = 层选.value;
      状.偏 = 0;
      读一页();
    });
    刷.addEventListener('click', () => {
      状.词 = 词框.value.trim();
      状.来源 = 源框.value.trim();
      状.偏 = 0;
      读一页();
    });
    词框.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') 刷.click();
    });

    async function 搜() {
      const 词 = 搜框.value.trim();
      if (!词) {
        搜果.textContent = '先写要搜的话。';
        return;
      }
      搜果.textContent = '检索中…（语义检索需经嵌入模型）';
      let d;
      try {
        d = await (await fetch(
          '/api/库/搜?词=' + encodeURIComponent(词) + '&层=' + 搜层.value + '&数=20'
        )).json();
      } catch (e) {
        搜果.textContent = '搜索失败：' + e;
        return;
      }
      搜果.textContent = '';
      const 讯 = document.createElement('div');
      讯.className = '库果讯';
      if (d.说明) {
        讯.textContent = '搜索失败：' + d.说明;
        讯.classList.add('坏');
      } else {
        讯.textContent = `${d.走 || ''}　｜　${层名[d.层] || d.层}（共 ${d.该层共 ?? '?'} 条）　｜　命中 ${(d.命中 || []).length} 条`;
      }
      搜果.appendChild(讯);
      (d.命中 || []).forEach((r) => {
        const 块 = document.createElement('div');
        块.className = '库果块';
        const 头 = document.createElement('div');
        头.className = '库果头';
        头.textContent = `#${r.rank}　score ${Number(r.score || 0).toFixed(4)}　${String(r.source || '').split('/').pop()}`;
        const 文 = document.createElement('div');
        文.className = '库果文';
        文.textContent = String(r.text || '').slice(0, 600);
        块.append(头, 文);
        搜果.appendChild(块);
      });
    }
    搜钮.addEventListener('click', 搜);
    搜框.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') 搜();
    });

    读概览();
    读一页();
    return 节;
  }

  // ───────────── 设置页·Skill（开关 + 搜索, 与 agent 走同一条检索）─────────────
  function 铺技能() {
    const 节 = 设节(
      'Skill',
      '开关落盘在 config/sub_agent.json 的 skills 段 —— 关掉的 skill 不进候选, agent 挑的时候直接看不到它, 立刻生效不用重启。下面那个搜索框走的是 agent 自己那条检索, 搜出来的就是它真会挑到的那几个。'
    );
    const 概 = document.createElement('div');
    概.className = '库概';
    概.textContent = '正在读配置…';
    节.appendChild(概);

    const 名册 = document.createElement('div');
    名册.className = '设表';
    节.appendChild(名册);

    const 搜题 = document.createElement('div');
    搜题.className = '库搜题';
    搜题.textContent = '检索（同一算法：agent 挑 skill 时走的就是这条）';
    const 搜栏 = document.createElement('div');
    搜栏.className = '库栏';
    const 搜框 = document.createElement('input');
    搜框.className = '库框 宽';
    搜框.type = 'search';
    搜框.placeholder = '所需能力 —— 例如「把 PDF 转成 markdown」';
    const 搜钮 = document.createElement('button');
    搜钮.type = 'button';
    搜钮.className = '库刷';
    搜钮.textContent = '搜';
    搜栏.append(搜框, 搜钮);
    const 搜果 = document.createElement('div');
    搜果.className = '库果';
    搜果.textContent = '输入一句话后点击「搜」。';
    节.append(搜题, 搜栏, 搜果);

    async function 读名册() {
      let d;
      try {
        d = await (await fetch('/api/技能')).json();
      } catch (e) {
        概.textContent = '读配置失败：' + e;
        概.classList.add('坏');
        return;
      }
      if (d.说明) {
        概.textContent = d.说明;
        概.classList.add('坏');
        return;
      }
      概.classList.remove('坏');
      const 全部 = d.技能 || [];
      概.textContent = `${全部.length} 个 skill —— 开着 ${全部.filter((x) => x.on).length} 个，关着 ${全部.filter((x) => !x.on).length} 个`;
      名册.textContent = '';
      全部.forEach((件) => {
        const 行 = document.createElement('label');
        行.className = '技行' + (件.on ? '' : ' 已关');
        const 文 = document.createElement('span');
        文.className = '技文';
        const 名 = document.createElement('span');
        名.className = '技名';
        名.textContent = 件.name;
        const 注 = document.createElement('span');
        注.className = '技注';
        注.textContent = 件.说明 || '';
        文.append(名, 注);
        const 字样 = document.createElement('span');
        字样.className = '技字';
        字样.textContent = 件.on ? '开' : '关';
        const 闸 = document.createElement('input');
        闸.type = 'checkbox';
        闸.dataset.技能 = '1';   // 它不走"保存"那条路(自己 POST), 别被记改动盯上
        闸.checked = 件.on;
        闸.addEventListener('change', async () => {
          闸.disabled = true;
          try {
            const r = await (await fetch('/api/技能/开关', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ 名: 件.name, 开: 闸.checked }),
            })).json();
            if (r.好 === false) {
              闸.checked = !闸.checked;
              window.alert(r.说明 || '写入失败');
            }
          } catch (e) {
            闸.checked = !闸.checked;
            window.alert('写入失败：' + e);
          } finally {
            闸.disabled = false;
            字样.textContent = 闸.checked ? '开' : '关';
            行.classList.toggle('已关', !闸.checked);
            读名册();
          }
        });
        行.append(文, 字样, 闸);
        名册.appendChild(行);
      });
    }

    async function 搜() {
      const 词 = 搜框.value.trim();
      if (!词) {
        搜果.textContent = '先写要办的事。';
        return;
      }
      搜果.textContent = '检索中…（需计算向量）';
      let d;
      try {
        d = await (await fetch('/api/技能/搜?词=' + encodeURIComponent(词))).json();
      } catch (e) {
        搜果.textContent = '检索失败：' + e;
        return;
      }
      搜果.textContent = '';
      const 讯 = document.createElement('div');
      讯.className = '库果讯';
      if (d.说明) {
        讯.textContent = d.说明;
        讯.classList.add('坏');
      } else {
        const 关 = d.关掉的 || [];
        讯.textContent = `${(d.命中 || []).length} 个候选　｜　关掉的已剔除（${关.length ? 关.join(' ') : '无'}）`;
      }
      搜果.appendChild(讯);
      (d.命中 || []).forEach((r, i) => {
        const 块 = document.createElement('div');
        块.className = '库果块';
        const 头 = document.createElement('div');
        头.className = '库果头';
        头.textContent = `#${i + 1}　${r.name}　score ${Number(r.score || 0).toFixed(4)}`;
        const 文 = document.createElement('div');
        文.className = '库果文';
        文.textContent = String(r.说明 || '').slice(0, 300);
        块.append(头, 文);
        搜果.appendChild(块);
      });
    }
    搜钮.addEventListener('click', 搜);
    搜框.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') 搜();
    });

    读名册();
    return 节;
  }

  function 铺现状(数) {
    const 节 = 设节('现状（只读）');
    for (const [题, 块] of Object.entries(数)) {
      if (题 === '接口' || 题 === '开关') continue;
      const 小 = document.createElement('div');
      小.className = '设卡';
      const 头 = document.createElement('div');
      头.className = '设题';
      头.textContent = 题;
      小.appendChild(头);
      if (Array.isArray(块)) {
        // ★ 一条一行 —— 13 个 skill 挤成 "a / b / c …" 谁都读不下去(2026-10-11 老板问"这个是啥")
        块.forEach((条, 序) => {
          小.appendChild(设行(String(序 + 1).padStart(2, '0'), String(条)));
        });
      } else {
        for (const [键, 值] of Object.entries(块 || {})) {
          if (值 === '') continue;
          if (值 === true) 小.appendChild(设行(键, '开', '开'));
          else if (值 === false) 小.appendChild(设行(键, '关', '关'));
          else 小.appendChild(设行(键, String(值)));
        }
      }
      节.appendChild(小);
    }
    return 节;
  }

  // ───────────── 设置页·定时任务（看挂着几条 / 撤一条；写操作走 POST）─────────────
  function 铺定时() {
    const 节 = 设节(
      '定时任务',
      '这是这个进程（web）自己那张表 —— 到点由它把提醒交回 agent：阻塞式就在对话里读秒，非阻塞式到点注入下一轮。撤掉之后不再提醒。'
    );
    const 卡 = document.createElement('div');
    卡.className = '设卡';
    const 头 = document.createElement('div');
    头.className = '设题';
    头.textContent = '挂着几条';
    卡.appendChild(头);
    节.appendChild(卡);

    async function 刷新() {
      卡.querySelectorAll('.定行, .定空, .设果').forEach((n) => n.remove());
      let 数;
      try {
        数 = await (await fetch('/api/定时')).json();
      } catch (e) {
        卡.appendChild(设行('读失败', String(e), '坏'));
        return;
      }
      if (数.说明) {
        卡.appendChild(设行('说明', String(数.说明), '坏'));
        return;
      }
      if (!数.挂着 || !数.挂着.length) {
        const 空 = document.createElement('div');
        空.className = '设行 定空';
        空.textContent = `现在是空的（表 ${数.表 || '?'}；线程${数.线程活着 ? '活着' : '没起'}）`;
        卡.appendChild(空);
        return;
      }
      数.挂着.forEach((条) => {
        const 行 = document.createElement('div');
        行.className = '设行 定行';
        const 左 = document.createElement('span');
        左.className = '设键';
        左.textContent = `${条.阻塞 ? '阻塞' : '非阻塞'} · ${条.到点说法 || ''}`;
        const 右 = document.createElement('span');
        右.className = '设值';
        右.textContent = String(条.提醒 || '');
        const 撤 = document.createElement('button');
        撤.type = 'button';
        撤.className = '库刷';
        撤.textContent = '撤';
        撤.addEventListener('click', async () => {
          撤.disabled = true;
          撤.textContent = '…';
          try {
            const r = await (await fetch('/api/定时/撤', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ id: 条.id }),
            })).json();
            if (r.好 === false) window.alert(r.说明 || '没撤掉');
          } catch (e) {
            window.alert('没撤掉：' + e);
          }
          刷新();
        });
        行.append(左, 右, 撤);
        卡.appendChild(行);
      });
    }
    刷新();
    return 节;
  }

  function 铺设置(数) {
    设置页.textContent = '';
    const 头 = document.createElement('div');
    头.className = '设头';
    const 标题 = document.createElement('h2');
    标题.textContent = '设置';
    const 说明 = document.createElement('p');
    说明.textContent = '在左侧选择一节。修改后点击底部保存 —— 写入本机配置文件（.env / config/*.json / skill/*/resources/*.json），下一问即按新值执行。';
    头.append(标题, 说明);

    const 条 = document.createElement('div');
    条.className = '保条';
    const 钮 = document.createElement('button');
    钮.type = 'button';
    钮.className = '保钮';
    钮.textContent = '保存';
    钮.addEventListener('click', () => 存设置(钮));
    const 果 = document.createElement('div');
    果.className = '设果';
    果.textContent = '还没改过';
    条.append(钮, 果);

    // 一节一条: 名字 + 现造。★ 每次切过去都重新造一遍(不缓存 DOM)——
    //   接口/开关那两节读的是活配置, 数据库/Skill 读的是活库, 缓存了就会给人看旧值。
    const 各节 = [
      ['接口', () => 铺接口(数)],
      ['开关', () => 铺开关(数)],
      ['Skill', () => 铺技能()],
      ['数据库', () => 铺数据库()],
      ['定时任务', () => 铺定时()],
      ['日志', () => 铺日志()],
      ['现状', () => 铺现状(数)],
      ['关闭', () => 铺关闭()],
    ];
    // 保存条只跟着"改得动"的节走, 只读的节上摆个保存按钮是噪音
    const 可改 = new Set(['接口', '开关']);

    const 壳 = document.createElement('div');
    壳.className = '设壳';
    const 左 = document.createElement('nav');
    左.className = '设栏';
    const 右 = document.createElement('div');
    右.className = '设区';
    壳.append(左, 右);

    let 当前 = localStorage.getItem('设置节') || 各节[0][0];
    if (!各节.some(([名]) => 名 === 当前)) 当前 = 各节[0][0];

    const 钮表 = new Map();
    const 切 = (名) => {
      当前 = 名;
      localStorage.setItem('设置节', 名);
      钮表.forEach((b, n) => b.classList.toggle('在', n === 名));
      右.textContent = '';
      // ★ 离开"日志"节要把它的自动刷收掉（DOM 扔了, 旧计时器不会自己停）
      if (typeof window.__日志计时 === 'function') { window.__日志计时(); window.__日志计时 = null; }
      // ★ 同理: 别节自己挂的计时器(关闭节那个 5 秒状态刷)也在这儿收
      if (typeof window.__节计时 === 'function') { window.__节计时(); window.__节计时 = null; }
      const 找 = 各节.find(([n]) => n === 名);
      if (!找) return;
      右.appendChild(找[1]());
      if (可改.has(名)) 右.appendChild(条);
      右.querySelectorAll('.设表行 input, .开关行 input:not([data-技能])').forEach((框) => {
        框.addEventListener('input', 记改动);
        框.addEventListener('change', 记改动);
      });
      记改动();
    };

    各节.forEach(([名]) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = '设钮';
      b.textContent = 名;
      b.addEventListener('click', () => 切(名));
      钮表.set(名, b);
      左.appendChild(b);
    });

    设置页.append(头, 壳);
    切(当前);
  }

  // 字节数说人话
  function 字节读(数) {
    const n = Number(数 || 0);
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }

  // ── 日志 ──
  // 分类按"谁产生的"分。只读尾巴 —— 主模型那个 log 跑一天能到几十 MB, 整个拽到浏览器是耍流氓。
  function 铺日志() {
    const 节 = 设节(
      '日志',
      '按"谁产生的"分。选一类看它最后几百行（不把整个文件拽过来）；盯活服务时开"自动刷"。目录类（执行记录 / 外援记账 / 交叉验证）看的是里面最新的那个文件。'
    );
    const 状 = { 名: '', 行: 300, 计时: null };

    const 列 = document.createElement('div');
    列.className = '日志列';
    节.appendChild(列);

    const 头 = document.createElement('div');
    头.className = '日志头';
    const 题 = document.createElement('span');
    题.className = '日志题';
    题.textContent = '（上面点一类）';
    头.appendChild(题);

    const 行选 = document.createElement('select');
    行选.className = '日志选';
    [100, 300, 1000].forEach((n) => {
      const o = document.createElement('option');
      o.value = String(n);
      o.textContent = '最后 ' + n + ' 行';
      if (n === 300) o.selected = true;
      行选.appendChild(o);
    });
    头.appendChild(行选);

    const 刷钮 = document.createElement('button');
    刷钮.className = '设钮 日志刷';
    刷钮.textContent = '刷新';
    头.appendChild(刷钮);

    const 自动 = document.createElement('label');
    自动.className = '日志自动';
    const 勾 = document.createElement('input');
    勾.type = 'checkbox';
    自动.appendChild(勾);
    自动.appendChild(document.createTextNode('自动刷（3秒）'));
    头.appendChild(自动);
    节.appendChild(头);

    const 框 = document.createElement('pre');
    框.className = '日志框';
    框.textContent = '（在上方选择一类日志）';
    节.appendChild(框);

    async function 拉() {
      if (!状.名) return;
      try {
        const d = await (await fetch('/api/日志/看?名=' + encodeURIComponent(状.名) + '&行=' + 状.行)).json();
        if (!d.行 || !d.行.length) {
          框.textContent = d.说明 || '（该类暂无内容）';
          return;
        }
        题.textContent = 状.名 + '　' + d.文件 + '　共 ' + d.共 + ' 行 / ' + 字节读(d.字节) + '　最后写入 ' + d.改于;
        框.textContent = d.行.join('\n');
        框.scrollTop = 框.scrollHeight;   // 看日志看的是最新那头
      } catch (错) {
        框.textContent = '读不了: ' + 错;
      }
    }

    async function 铺类() {
      let 类 = [];
      try {
        类 = (await (await fetch('/api/日志')).json()).类 || [];
      } catch (错) {
        列.textContent = '列不出日志: ' + 错;
        return;
      }
      if (!类.length) { 列.textContent = '没有日志'; return; }
      列.textContent = '';
      类.forEach((一) => {
        const b = document.createElement('button');
        b.className = '日志类' + (一.有 ? '' : ' 空');
        b.dataset.名 = 一.名;
        b.title = 一.说明 + (一.何时 ? ' · ' + 一.何时 : '');
        const 名 = document.createElement('b');
        名.textContent = 一.名;
        b.appendChild(名);
        const 小 = document.createElement('span');
        // ★ 空的时候别只写「还没有」—— 会被读成"没接线"。把"什么时候才会有"的实话带上。
        小.textContent = 一.有
          ? (一.目录 ? 一.个数 + ' 个 · ' : '') + 字节读(一.字节) + ' · ' + 一.改于
          : (一.何时 ? '还没有 · ' + 一.何时 : '还没有');
        b.appendChild(小);
        b.addEventListener('click', () => {
          状.名 = 一.名;
          [...列.querySelectorAll('.日志类')].forEach((x) => x.classList.toggle('选', x.dataset.名 === 状.名));
          拉();
        });
        列.appendChild(b);
      });
    }

    刷钮.addEventListener('click', 拉);
    行选.addEventListener('change', () => { 状.行 = Number(行选.value); 拉(); });
    勾.addEventListener('change', () => {
      if (状.计时) { clearInterval(状.计时); 状.计时 = null; }
      if (勾.checked) 状.计时 = setInterval(拉, 3000);
    });
    // ★ 计时器挂到 window: 切到别的节时"切()"会把这块 DOM 扔掉, 但 setInterval
    //   还活着 —— 那样它会一直在后台每 3 秒拉一次, 白耗。
    window.__日志计时 = () => { if (状.计时) { clearInterval(状.计时); 状.计时 = null; } };

    铺类();
    return 节;
  }

  // ── 关闭 ──
  // ★ 都是"点了就没了", 所以按钮要点第二下才真动手。
  // ★ 顶上带一排实时状态(5 秒一刷): 这一节的活就是关掉"正在跑的东西" ——
  //   不告诉你现在哪个在跑, 等于让你闭着眼点(2026-10-11 老板问"这个是啥")。
  //   没在跑的那个按钮直接置灰: 没什么可关的。
  function 铺关闭() {
    const 节 = 设节(
      '关闭',
      '关掉正在跑的东西。都是不可逆的（关完要再起来, 回启动页点「以本地模型启动」），所以按钮要点第二下才动手。' 
    );

    const 状卡 = document.createElement('div');
    状卡.className = '设卡';
    const 状题 = document.createElement('div');
    状题.className = '设题';
    状题.textContent = '当前运行项（每 5 秒刷新）';
    const 状行 = document.createElement('div');
    状行.className = '关状';
    状卡.append(状题, 状行);
    节.appendChild(状卡);

    const 行 = document.createElement('div');
    行.className = '关行';
    节.appendChild(行);

    const 灯表 = {};
    ['PG', '主模型', '向量', 'web'].forEach((名) => {
      const 片 = document.createElement('span');
      片.className = '关灯';
      const 点 = document.createElement('i');
      const 字 = document.createElement('b');
      字.textContent = 名;
      片.append(点, 字);
      状行.appendChild(片);
      灯表[名] = 片;
    });

    const 卡们 = [];
    function 造卡(标题, 说明, 目标, 险, 钮字, 看活) {
      const 卡 = document.createElement('div');
      卡.className = '关卡';
      const 题 = document.createElement('b');
      题.textContent = 标题;
      卡.appendChild(题);
      const 小 = document.createElement('span');
      小.textContent = 说明;
      卡.appendChild(小);
      const 钮 = document.createElement('button');
      钮.className = '关钮' + (险 ? ' 险' : '');
      钮.textContent = 钮字 || '关闭';
      卡.appendChild(钮);

      let 待 = 0;
      let 计 = null;
      const 回表 = () => {
        待 = 0;
        钮.textContent = 钮字 || '关闭';
        钮.classList.remove('待');
        if (计) { clearTimeout(计); 计 = null; }
      };
      钮.addEventListener('click', async () => {
        if (待 === 0) {
          待 = 1;
          钮.textContent = '再点一下确认';
          钮.classList.add('待');
          计 = setTimeout(() => { if (待 === 1) 回表(); }, 4000);
          return;
        }
        if (待 === 2) return;          // 已经在关了, 别重复发
        待 = 2;
        if (计) { clearTimeout(计); 计 = null; }
        钮.textContent = '正在关…';
        钮.disabled = true;
        try {
          const d = await (await fetch('/api/关闭', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 目标 }),
          })).json();
          小.textContent = (d.好 ? '✓ ' : '✗ ') + (d.说明 || '');
        } catch (错) {
          小.textContent = '✓ 已断开（关闭 agent 即会断开连接）—— ' + 错;
        }
        钮.textContent = '已关闭';
        刷状态();
      });
      行.appendChild(卡);
      卡们.push({ 钮, 看活, 钮字: 钮字 || '关闭' });
    }

    造卡('本地模型', '主模型(:8790) + 向量(:8199)。★ 先停看门狗再停模型 —— 否则 30 秒后看门狗会把模型重新拉起', '模型', false, '关闭模型', (态) => !!态.主模型 || !!态.向量);
    造卡('agent（这个网页）', '关闭 web 服务本身。页面会断开，属正常现象；需要时再运行 collaplex-agent web', 'agent', false, '关闭网页', (态) => !!态.web);
    造卡('模型与网页一并关闭（收工时使用）', '模型关闭与网页关闭一并执行，收工时使用', '全部', true, '全部关闭', () => true);

    async function 刷状态() {
      let 态 = {};
      try {
        态 = await (await fetch('/api/启动/状态')).json();
      } catch (错) {
        状行.textContent = '无法读取服务状态：' + 错;
        return;
      }
      Object.entries(灯表).forEach(([名, 片]) => {
        const 活 = !!态[名];
        片.classList.toggle('活', 活);
        片.title = 名 + (活 ? ' 在跑' : ' 没在跑');
      });
      卡们.forEach((卡) => {
        if (卡.钮.textContent === '正在关…') return;      // 正在关的别打扰
        卡.钮.disabled = !卡.看活(态);
        卡.钮.title = 卡.钮.disabled ? '当前未在运行 —— 无进程可关' : '';
      });
    }

    const 计时 = setInterval(刷状态, 5000);
    window.__节计时 = () => clearInterval(计时);   // 换节时由 切() 收掉
    刷状态();
    return 节;
  }

  // 数一数有几处待保存 —— 改没改、该不该点保存, 一眼看得出
  function 待保存() {
    let 数 = 0;
    设置页.querySelectorAll('.设表行').forEach((行) => {
      if (!行.dataset.组) return;
      const 端点 = 行.querySelector('.端点').value.trim();
      const 模型 = 行.querySelector('.模型').value.trim();
      const 钥 = 行.querySelector('.密钥').value.trim();
      if (钥 || 端点 !== (行.dataset.原端点 || '') || 模型 !== (行.dataset.原模型 || '')) 数 += 1;
    });
    设置页.querySelectorAll('.开关行').forEach((行) => {
      const 现在 = 行.querySelector('input').checked ? '1' : '0';
      if (现在 !== (行.dataset.原值 || '0')) 数 += 1;
    });
    return 数;
  }

  function 记改动() {
    const 数 = 待保存();
    const 钮 = 设置页.querySelector('.保钮');
    if (钮) 钮.disabled = 数 === 0;
    const 果 = 设置页.querySelector('.设果');
    if (!果 || 果.dataset.存过 === '1') return;
    果.textContent = 数 ? `${数} 处待保存` : '还没改过';
  }

  function 报果(已改) {
    const 果 = 设置页.querySelector('.设果');
    if (!果) return;
    果.className = '设果';
    果.textContent = '';
    const 头 = document.createElement('span');
    const 条们 = 已改 || [];
    头.textContent = 条们.length ? '已写入：' : '没有改动。';
    果.appendChild(头);
    条们.forEach((行) => {
      const 条 = document.createElement('span');
      条.className = '行';
      条.textContent = 行;
      果.appendChild(条);
    });
  }

  async function 存设置(钮) {
    const 果 = 设置页.querySelector('.设果');
    钮.disabled = true;
    钮.textContent = '保存中…';
    // ★ 只递交真改过的 —— 没动的一律不发, 免得"点一个开关"把四条接口全重写一遍
    const 接口 = [...设置页.querySelectorAll('.设表行')]
      .filter((行) => 行.dataset.组)
      .map((行) => {
        const 端点 = 行.querySelector('.端点').value.trim();
        const 模型 = 行.querySelector('.模型').value.trim();
        const 钥 = 行.querySelector('.密钥').value.trim();
        const 变了 = 钥 || 端点 !== (行.dataset.原端点 || '') || 模型 !== (行.dataset.原模型 || '');
        if (!变了) return null;
        const 项 = { 名: 行.dataset.组, 端点, 模型 };
        if (钥) 项.密钥 = 钥;      // 留空 = 不改密钥
        return 项;
      })
      .filter(Boolean);
    const 开关 = {};
    设置页.querySelectorAll('.开关行').forEach((行) => {
      const 现在 = 行.querySelector('input').checked ? '1' : '0';
      if (现在 !== (行.dataset.原值 || '0')) 开关[行.dataset.名] = 现在 === '1';
    });
    if (!接口.length && !Object.keys(开关).length) {
      钮.disabled = false;
      钮.textContent = '保存';
      报果([]);
      return;
    }
    try {
      const 回 = await fetch('/api/设置', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 接口, 开关 })
      }).then((响) => 响.json());
      if (回.错) throw new Error(回.错);
      铺设置(回.设置);
      报果(回.改了);
      设置页.querySelector('.设果').dataset.存过 = '1';
      记改动();
      刷新状态();
    } catch (错) {
      果.className = '设果 坏';
      果.textContent = '存不上：' + (错 && 错.message ? 错.message : 错);
    }
    钮.disabled = false;
    钮.textContent = '保存';
  }

  function 切页(名) {
    在看设置 = (名 === '设置');
    设置页.hidden = !在看设置;
    对话区.hidden = 在看设置;
    底栏.hidden = 在看设置;
    到底.hidden = true;
    页眉.textContent = 在看设置 ? '设置' : (当前名 || '对话');
    页眉.title = 当前名 || '';
    设置钮.classList.toggle('在', 在看设置);
    if (!在看设置) { 问框.focus(); 状态行.textContent = '就绪'; }
    window.scrollTo({ top: 0 });
  }

  // 收起/展开侧栏 —— 选择记在 localStorage, 刷新不弹回; Ctrl/Cmd+B 同效
  if (localStorage.getItem('收栏') === '1') document.body.classList.add('收栏');
  收栏钮.addEventListener('click', () => {
    const 收 = document.body.classList.toggle('收栏');
    localStorage.setItem('收栏', 收 ? '1' : '0');
  });
  window.addEventListener('keydown', (一) => {
    if ((一.ctrlKey || 一.metaKey) && 一.key.toLowerCase() === 'b') {
      一.preventDefault();
      收栏钮.click();
    }
  });

  设置钮.addEventListener('click', () => {
    if (在看设置) { 切页('对话'); return; }
    切页('设置');
    fetch('/api/设置').then((响) => 响.json())
      .then((数) => 铺设置(数.设置))
      .catch(() => {
        设置页.textContent = '';
        const 卡 = document.createElement('div');
        卡.className = '设节';
        卡.textContent = '读取设置失败 —— 请查看服务端日志';
        设置页.appendChild(卡);
      });
  });

  // ─────────────────────────── 7. 发问: 收 SSE ───────────────────────────

  async function 发问(问题) {
    if (忙 || !问题.trim()) return;
    当前名 = '';                            // 新对话: 顶栏回到"对话"
    页眉.textContent = '对话';
    页眉.title = '';
    忙 = true;
    发送.disabled = true;
    状态行.textContent = '进行中…';
    空态.hidden = true;

    const 轮 = document.createElement('section');
    轮.className = '轮';
    轮.dataset.活 = '1';                        // 现场这轮: 正文还在流式长, 动态卸载别碰它
    const 问题块 = document.createElement('div');
    问题块.className = '问';
    问题块.textContent = 问题;
    const 答案块 = document.createElement('div');
    答案块.className = '答案 md';
    const 过程位 = document.createElement('div');
    过程位.className = '过程位';
    轮.append(问题块, 过程位, 答案块);
    流.appendChild(轮);

    const 过程 = new 过程面板(过程位);
    过程.忙着 = true;
    过程.详情.open = true;      // 干着的时候摊开 —— 过程要能看见, 不做黑盒
    const 答案 = new 流式答案(答案块);
    const 起 = performance.now();
    let 收到答案 = false;

    if (贴底() || document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) < 400) 回到底();

    try {
      const 响应 = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 问: 问题 })
      });
      if (!响应.ok || !响应.body) throw new Error('接口 ' + 响应.status);

      const 读 = 响应.body.getReader();
      const 解码 = new TextDecoder('utf-8');
      let 缓 = '';
      for (;;) {
        const { done, value } = await 读.read();
        if (done) break;
        缓 += 解码.decode(value, { stream: true });
        let 界;
        while ((界 = 缓.indexOf('\n\n')) >= 0) {
          const 帧 = 缓.slice(0, 界);
          缓 = 缓.slice(界 + 2);
          帧.split('\n').forEach((行) => {
            if (!行.startsWith('data:')) return;
            const 身体 = 行.slice(5).trim();
            if (!身体 || 身体 === '{}') return;
            let 事件;
            try { 事件 = JSON.parse(身体); } catch (错) { return; }
            收事件(事件);
          });
        }
      }
    } catch (错) {
      过程.收('error', '这条流断了：' + (错 && 错.message ? 错.message : 错));
    }

    function 收事件(事) {
      const 类 = 事.kind;
      if (类 === 'answer') {
        // ★ 边流边吐(2026-10-09 老板: "流式输出中断") —— 草稿进 流式答案.推(), 由它过一遍 去协议()
        //   再渲染: exec 那轮的 `<调用>…</调用>` 协议标记/判定 JSON 不流进正文区, 人话照流。
        //   跑完 final 一到, 定稿整块换掉草稿(一字不动)。
        收到答案 = true;
        答案.推(String(事.text || ''));
      } else if (类 === 'final') {
        答案.置(String(事.text || ''));
      } else if (类 === 'usage') {
        const 用 = 事.usage || {};
        if (用.tokens_per_second != null) {
          统计.textContent = `${Number(用.tokens_per_second).toFixed(2)} tok/s · 出 ${用.completion_tokens ?? '-'} tok`;
        }
      } else if (类 === 'done') {
        if (!收到答案 && !答案块.textContent) 答案块.textContent = '（本轮无正文输出）';
        // 服务端说这轮完了 —— 立刻收尾(别等连接关, 那多出来的一截是后台记账)
        答案.完成();
        过程.忙着 = false;
        过程.刷新总();
        过程.详情.open = false;   // 收尾: 过程折起来, 正文让位
        状态行.textContent = `这一轮用时 ${((performance.now() - 起) / 1000).toFixed(1)} 秒`;
      } else {
        过程.收(类, String(事.text || ''));
        if (类 === 'note' && /入二层库|入库/.test(String(事.text || ''))) {
          过程.详情.open = false;
        }
      }
      if (贴底()) 回到底();
    }

    答案.完成();
    过程.忙着 = false;
    过程.刷新总();
    状态行.textContent = `这一轮用时 ${((performance.now() - 起) / 1000).toFixed(1)} 秒`;
    忙 = false;
    发送.disabled = false;
    问框.focus();
    // 服务端这时才写完存档 —— 拉回来刷侧栏跳点, 顺手把这轮也算进"已载"
    await 拉目录();
    已载 += 1;
    高亮(总 - 1);
  }

  问表.addEventListener('submit', (事) => {
    事.preventDefault();
    const 问题 = 问框.value;
    问框.value = '';
    问框.style.height = 'auto';
    发问(问题);
  });

  function 刷新状态() {
    return fetch('/api/state').then((响) => 响.json()).then(铺状态).catch(() => {
      状态行.textContent = '无法获取服务状态';
    });
  }

  // 一打开: 只摆最新一批(一批=10 轮)并落在最新的那轮上; 往上翻再懒加载更早的
  (async () => {
    await 拉目录();
    const 回 = await 取一段(0, 一批);
    if (回 && (回.段 || []).length) {
      回.段.forEach((条) => 数据.set(Number(条.序号), 条));
      回.段.forEach((条) => 挂一轮(Number(条.序号)));
      已载 = 回.段.length;
      还有更早 = !!回.还有更早的;
      空态.hidden = true;
      哨兵.textContent = 还有更早 ? '上拉加载更早记录' : '';
      // 落到底: 摆完先落一次, 再补两拍(布局还会动) —— 之后图块/公式/字体把页面顶高的部分
      // 交给 定在底 的 ResizeObserver 一路跟到最新。
      落到底();
      requestAnimationFrame(() => { 落到底(); requestAnimationFrame(落到底); });
      平衡();
    }
    高亮(总 - 1);
    刷新状态();
  })();

  // ───────────── 编排清单面板（输入框上面；清单撤了就自己消失）─────────────
  // 数据来自 GET /api/清单（冷库表 orchestra）——挂着的清单画出来、没有就藏起来。
  // 不靠 SSE: 每 2.5 秒看一次就够(清单在一轮里推进, 不是高频)。
  const 清单栏 = document.getElementById('清单栏');
  let 清单收起 = false;
  const 清单图标 = { '好了': '✅', '在做': '◈', '待做': '○', '卡住': '⚠' };
  const 洗字 = (s) => String(s === undefined || s === null ? '' : s)
    .replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

  function 画清单(全单) {
    const 对话们 = Object.keys(全单 || {});
    if (!对话们.length) {
      清单栏.hidden = true;
      清单栏.innerHTML = '';
      return;
    }
    const 段 = [];
    for (const 对话 of 对话们) {
      const 单 = 全单[对话] || [];
      const 好了 = 单.filter((条) => 条.状态 === '好了').length;
      段.push('<div class="清单头">');
      段.push('<span class="清单题">任务 ' + 好了 + '/' + 单.length
        + (对话们.length > 1 ? ' · ' + 洗字(对话) : '') + '</span>');
      段.push('<span class="清单折">' + (清单收起 ? '展开' : '收起') + '</span></div>');
      if (!清单收起) {
        for (const 条 of 单) {
          段.push('<div class="清单行 状-' + 洗字(条.状态) + '">'
            + '<span class="清单号">' + 洗字(条.序号) + '</span>'
            + '<span class="清单说">' + 洗字(条.说明) + '</span>'
            + '<span class="清单态">' + (清单图标[条.状态] || '·') + ' '
            + 洗字(条.状态) + '</span></div>');
        }
      }
    }
    清单栏.innerHTML = 段.join('');
    清单栏.hidden = false;
  }

  async function 铺清单() {
    try {
      const 回 = await (await fetch('/api/清单')).json();
      画清单(回.清单 || {});
    } catch (e) {
      // 冷库不通就别摆面板, 不打扰输入
    }
  }

  清单栏.addEventListener('click', (e) => {
    if (e.target.closest('.清单头')) {
      清单收起 = !清单收起;
      铺清单();
    }
  });
  铺清单();
  setInterval(铺清单, 2500);
})();
