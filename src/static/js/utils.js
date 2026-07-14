function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function isDirType(type) { return type === 'dir'; }
function isMarkdownType(filepath) {
    if (!filepath) return false;
    return /\.(md|markdown)$/i.test(filepath);
}
function isImageType(filepath) {
    if (!filepath) return false;
    return /\.(png|jpg|jpeg|gif|svg|webp)$/i.test(filepath);
}

const CODE_LANG_MAP = {
    // YAML
    'yml': 'yaml',
    'yaml': 'yaml',
    // Shell
    'sh': 'shell',
    'bash': 'shell',
    // C/C++
    'c': 'c',
    'cpp': 'cpp',
    'cc': 'cpp',
    'h': 'c',
    'hpp': 'cpp',
    // Web
    'html': 'html',
    'htm': 'html',
    'css': 'css',
    'scss': 'scss',
    'less': 'less',
    'js': 'javascript',
    'ts': 'typescript',
    // 后端语言
    'py': 'python',
    'go': 'go',
    'java': 'java',
    'rs': 'rust',
    'php': 'php',
    'rb': 'ruby',
    'swift': 'swift',
    'kt': 'kotlin',
    'dart': 'dart',
    // 配置/数据
    'json': 'json',
    'xml': 'xml',
    'ini': 'ini',
    'conf': 'ini',
    'cfg': 'ini',
    'env': 'bash',
};

/**
 * 根据文件名获取代码语言标识
 */
function getCodeLang(filepath) {
    if (!filepath) return 'plaintext';
    const ext = filepath.split('.').pop().toLowerCase();
    return CODE_LANG_MAP[ext] || 'plaintext';
}

/**
 * 判断是否为代码文件（需要高亮的类型）
 */
function isCodeType(filepath) {
    if (!filepath) return false;
    // 后缀 -> 语言标识的映射表（后面要用）
    return /\.(json|ya?ml|xml|html?|css|scss|less|js|ts|py|go|java|c|cpp|cc|h|hpp|rs|sh|bash|php|rb|swift|kt|dart)$/i.test(filepath);
}

/**
 * 判断是否为纯文本文件（不需要高亮，用原来的 plain-text-preview 包裹）
 */
function isPlainTextType(filepath) {
    if (!filepath) return false;
    return /\.(txt|text|log|ini|conf|cfg|env|gitignore|dockerignore)$/i.test(filepath);
}

// 原来的 isTextType 可以保留作为兜底，也可以直接废弃
function isTextType(filepath) {
    return isCodeType(filepath) || isPlainTextType(filepath) || isMarkdownType(filepath);
}

function getFilename(filepath) {
    // /a/b.txt => b.txt
    return filepath.replace(/\/+$/, '').split('/').pop() || '';
}

function isSameExt(a, b) {
    // 比较两个文件的扩展名是否相同，大小写不敏感
    return a.toLowerCase().match(/\.\w+$/)?.[0] === b.toLowerCase().match(/\.\w+$/)?.[0];
}

function rStripSlash(path) {
    // 去掉右侧的斜杠，处理空字符串和全斜杠的情况
    return path.replace(/\/+$/, '');
}

function lStripSlash(path) {
    // 去掉左侧的斜杠，处理空字符串和全斜杠的情况
    return path.replace(/^\/+/, '');
}

// ============================
// [DIFF] 前端 diff 计算（基于 google/diff-match-patch）
// ============================
function computeDiff(oldStr, newStr) {
    const dmp = new diff_match_patch();
    let diff = dmp.diff_main(oldStr, newStr);
    dmp.diff_cleanupSemantic(diff);
    return diff.map(item => ({
        count: [...item[1]].length,
        added: item[0] === 1,
        removed: item[0] === -1,
        value: item[1]
    }));
}

function generateDiffHtml(oldStr, newStr) {
    const diff = computeDiff(oldStr, newStr);
    let html = '';
    for (const d of diff) {
        const encoded = escapeHtml(d.value);
        if (d.removed) {
            html += `<span style="text-decoration: line-through; background-color: #ffd0d4; color: #c00;">${encoded}</span>`;
        } else if (d.added) {
            html += `<span style="color: #3c744a; background-color: #b6ecbf;">${encoded}</span>`;
        } else {
            html += `<span style="color: #555;">${encoded}</span>`;
        }
    }
    // 用 pre 标签保持换行和空格
    return `<pre style="font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 1.6; margin: 0; white-space: pre-wrap; word-break: break-all;">${html}</pre>`;
}

// ============================
// [MERGE] 前端合并内容（对应后端 merge_content 逻辑）
// ============================
function mergeContent(baseContent, diff) {
    let result = [];
    let index = 0;
    for (const d of diff) {
        if (d.added) {
            result.push(d.value);
        } else if (d.removed) {
            index += d.count;
        } else {
            result.push(baseContent.substring(index, index + d.count));
            index += d.count;
        }
    }
    result.push(baseContent.substring(index));
    return result.join('');
}

/**
 * 解析相对路径为绝对路径
 * @param {string} baseDir - 基础目录（Markdown 文件所在目录）
 * @param {string} relativePath - 相对路径
 * @returns {string} 绝对路径
 */
function resolveRelativePath(baseDir, relativePath) {
    const stack = baseDir.split('/').filter(p => p);
    const parts = relativePath.split('/').filter(p => p);

    for (const part of parts) {
        if (part === '..') {
            stack.pop();
        } else if (part !== '.') {
            stack.push(part);
        }
    }

    return '/' + stack.join('/');
}
/**
 * Front Matter Parser (Strict Mode)
 * - 零宽容语法校验
 * - 精确行号报错
 * - 支持 Jekyll 标准列表
 * - 符合 GFM 横向表格规范
 */

const _FM_MAX_SCAN = 4096;
const _FM_MAX_COLS = 5;

// 快速判断换行
function _fm_isBr(ch) {
    return ch === 0x0a || ch === 0x0d;
}

// 移除字符串首尾引号
function _fm_stripQuotes(v) {
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        return v.slice(1, -1);
    }
    return v;
}

// 解析 flow 数组 [a, b, c]
function _fm_parseFlowArray(raw) {
    const s = raw.trim();
    if (!s.startsWith('[') || !s.endsWith(']')) return null;
    return s
        .slice(1, -1)
        .split(',')
        .map(v => _fm_stripQuotes(v.trim()))
        .filter(v => v.length > 0)
        .join(', ');
}

// 校验是否为合法列表项（必须以 "- " 开头且缩进）
function _fm_isListItem(line, indent) {
    const trimmed = line.slice(indent);
    return trimmed.startsWith('- ') && trimmed.length > 2;
}

// 构建 GFM 横向表格（最多5列，不足补空）
function _fm_buildTable(keys, values) {
    const tables = [];
    for (let i = 0; i < keys.length; i += _FM_MAX_COLS) {
        const rowKeys = keys.slice(i, i + _FM_MAX_COLS);
        const rowVals = values.slice(i, i + _FM_MAX_COLS);
        // 补空列
        while (rowKeys.length < _FM_MAX_COLS) {
            rowKeys.push('');
            rowVals.push('');
        }
        const header = `| ${rowKeys.map(k => k ? `**${k}**`: '-').join(' | ')} |`;
        const divider = `| ${rowKeys.map(() => '--').join(' | ')} |`;
        const body = `| ${rowVals.join(' | ')} |`;
        tables.push(`${header}\n${divider}\n${body}`);
    }
    return tables.join('\n\n');
}

function _parseFrontMatter(content) {
    if (typeof content !== 'string' || content.length < 4) {
        return { status: null, log: '', content };
    }

    // ===== 快速路径1：起始标记严格校验 =====
    // 前3个字符必须是 ---
    if (content.charCodeAt(0) !== 0x2d || content.charCodeAt(1) !== 0x2d || content.charCodeAt(2) !== 0x2d) {
        return { status: null, log: '', content };
    }
    // 第4个字符必须是换行（\n 或 \r\n）
    const fourthChar = content.charCodeAt(3);
    let fmStart = 0;
    let line = 1; // 行号从1开始
    if (fourthChar === 0x0a) {
        fmStart = 4;
    } else if (fourthChar === 0x0d) {
        if (content.charCodeAt(4) === 0x0a) {
            fmStart = 5;
        } else {
            fmStart = 4;
        }
    } else {
        // 第1行：---后面不是换行，而是其他字符（比如你给的例子中---后的----）
        return {
            status: -1,
            log: `第${line}行：Front Matter起始标记格式错误，应为 "---" 后紧跟换行，而非其他字符`,
            content
        };
    }

    // 限制扫描范围为前4KB
    const scanLimit = Math.min(content.length, fmStart + _FM_MAX_SCAN);
    let endPos = -1;
    let endLine = -1;
    let pos = fmStart;
    let currentLine = 2; // 起始---之后的第一行是行2
    let lastLineEnd = fmStart;

    // ===== 扫描结束标记 ---，严格校验整行只有--- =====
    while (pos < scanLimit) {
        const ch = content.charCodeAt(pos);
        if (_fm_isBr(ch)) {
            // 检查当前行是否是 ---
            const lineContent = content.slice(lastLineEnd, pos).trim();
            if (lineContent === '---') {
                endPos = lastLineEnd;
                endLine = currentLine;
                break;
            }
            // 跳过换行，更新行号
            if (ch === 0x0d && content.charCodeAt(pos + 1) === 0x0a) {
                pos++;
            }
            lastLineEnd = pos + 1;
            currentLine++;
        }
        pos++;
    }

    // 4KB内没找到合法结束标记
    if (endPos === -1) {
        return {
            status: -1,
            log: `未找到合法的结束标记 "---"（已扫描前${_FM_MAX_SCAN}字节，当前行号：${currentLine}），结束标记必须单独占一行且无其他字符`,
            content
        };
    }

    // 提取FM内容和正文
    const fmText = content.slice(fmStart, endPos);
    const bodyStart = endPos + 3 + (content.charCodeAt(endPos + 3) === 0x0d && content.charCodeAt(endPos + 4) === 0x0a ? 2 : 1);
    const body = content.slice(bodyStart);

    // ===== 解析FM内容，严格校验每一行 =====
    const fmObj = {};
    let pendingKey = null; // 等待列表值的键（比如 categories: 后跟着 - 教程）
    const lines = fmText.split(/\r?\n/);
    let parseLine = 2; // 对应实际行号，起始---是第1行，FM内容从第2行开始

    for (const rawLine of lines) {
        const trimmed = rawLine.trim();
        // 跳过空行和注释
        if (trimmed.length === 0 || trimmed.startsWith('#')) {
            parseLine++;
            continue;
        }

        // 处理列表项（必须在pendingKey存在的情况下）
        const indent = rawLine.match(/^\s*/)[0].length;
        if (_fm_isListItem(rawLine, indent)) {
            if (pendingKey === null) {
                return {
                    status: -1,
                    log: `第${parseLine}行：非法的列表项，列表必须紧跟在 "key:" 定义之后`,
                    content
                };
            }
            const itemVal = _fm_stripQuotes(rawLine.slice(indent + 2).trim());
            fmObj[pendingKey] = fmObj[pendingKey] ? `${fmObj[pendingKey]}, ${itemVal}` : itemVal;
            parseLine++;
            continue;
        }

        // 处理键值对：必须包含且仅包含一个冒号
        const colonIdx = trimmed.indexOf(':');
        if (colonIdx <= 0) {
            return {
                status: -1,
                log: `第${parseLine}行：非法的键值对格式，缺少冒号或冒号在行首（示例：key: value）`,
                content
            };
        }

        const key = trimmed.slice(0, colonIdx).trim();
        const valRaw = trimmed.slice(colonIdx + 1).trim();

        if (key.length === 0) {
            return {
                status: -1,
                log: `第${parseLine}行：键不能为空，冒号前必须有有效键名`,
                content
            };
        }

        // 处理值：优先解析flow数组，否则去引号
        let val = _fm_parseFlowArray(valRaw);
        if (val === null) {
            val = _fm_stripQuotes(valRaw).replace(/\|/g, '\\|');
        }

        // 如果值为空，标记为pendingKey，等待后续列表项
        if (valRaw.length === 0) {
            pendingKey = key;
            fmObj[key] = '';
        } else {
            pendingKey = null;
            fmObj[key] = val;
        }

        parseLine++;
    }

    // 校验是否有未闭合的列表（pendingKey不为空但没有后续列表项）
    if (pendingKey !== null && fmObj[pendingKey] === '') {
        return {
            status: -1,
            log: `第${parseLine - 1}行：键 "${pendingKey}:" 定义为空但未跟随列表项`,
            content
        };
    }

    const keys = Object.keys(fmObj);
    const values = keys.map(k => fmObj[k]);
    const table = _fm_buildTable(keys, values);

    return {
        status: 1,
        log: '',
        content: `${table}\n\n${body}`
    };
}

function renderMarkdown(content, filePath, username, domain) {
    const baseDir = filePath.split('/').slice(0, -1).join('/');

    // 自定义 Renderer 处理图片路径
    const renderer = new marked.Renderer();
    const originalImage = renderer.image;

    // ✅ 核心修正：用对象解构接收参数
    renderer.image = (token) => {
        // 从 token 对象里解构出需要的属性，加兜底处理
        const { href: rawHref, title: rawTitle, text: rawAlt } = token;
        const href = rawHref?.trim() || '';
        const alt = rawAlt || '';
        const finalTitle = rawTitle || '';

        // 白名单：不处理的 URL 模式
        if (!href ||
            /^(https?:)?\/\//i.test(href) ||
            href.startsWith('data:') ||
            href.startsWith('blob:') ||
            href.startsWith('file:')
        ) {
            // ✅ 修正：调用原有 renderer 时直接传原 token，不用拆参数
            return originalImage.call(renderer, token);
        }

        // 处理 _style 自定义属性
        const styleRegex = /_style=\{(.*?)\}/;
        const styleMatch = alt.match(styleRegex);
        const styleValue = styleMatch ? styleMatch[1] : '';
        const cleanAlt = alt.replace(styleRegex, '').trim();

        // 拼接绝对路径
        let absolutePath;
        if (href.startsWith('/')) {
            absolutePath = href;
        } else {
            absolutePath = resolveRelativePath(baseDir, href);
        }

        const fullUrl = `/notebook/img_preview/${username}/${domain}${absolutePath}`;

        // 生成带错误处理和懒加载的 img 标签
        return `<div class="image-preview">
                <img src="${fullUrl}"
                     alt="${cleanAlt}"
                     title="${finalTitle}"
                     loading="lazy"
                     style="${styleValue}"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
            </div>`;
    };

    // 渲染 Markdown
    // 首先提取 FM 的部分
    const fmResult = _parseFrontMatter(content);
    const rawHtml = marked.parse(fmResult.content, { renderer });

    const html = DOMPurify.sanitize(rawHtml, {
        ADD_TAGS: ['img'],
        ADD_ATTR: ['src', 'alt', 'title', 'loading', 'style', 'onerror'], // 必须加 onerror
        FORBID_TAGS: ['script', 'style', 'link', 'meta'],
        FORBID_ATTR: ['onload', 'onclick', 'onmouseover'] // 只禁止不需要的事件
    });

    return {status: fmResult.status, log: fmResult.log, html: html}
}

/* ==================== 编辑器核心工具函数（新增部分） ==================== */
/**
 * 判断当前文件是否支持文本编辑
 * @param {string} fileId - 文件ID（路径）
 * @returns {boolean}
 */
function nb_isTextEditable(fileId) {
    return isTextType(fileId || '');
}

/**
 * 获取编辑器当前选区位置
 * @param {HTMLTextAreaElement} editor - textarea DOM实例
 * @returns {{start: number, end: number}}
 */
function nb_getEditorSelection(editor) {
    if (!editor || editor.tagName !== 'TEXTAREA') return { start: 0, end: 0 };
    return {
        start: editor.selectionStart,
        end: editor.selectionEnd
    };
}

/**
 * 编辑器键盘事件总入口（所有按键逻辑统一分发）
 * @param {KeyboardEvent} event - 键盘事件对象
 * @param {Object} ctx - 上下文对象
 * @param {HTMLTextAreaElement} ctx.editor - textarea DOM实例
 * @param {Function} ctx.isTextFile - 判断是否为文本文件的函数
 */
function nb_editorKeydownHandler(event, ctx) {
    const { editor } = ctx;

    // 前置校验：非文本文件/输入法输入中不干预（避免打断中文输入）
    if (!editor || event.isComposing) return;

    // 1. Tab/Shift+Tab：缩进控制
    if (event.key === 'Tab') {
        event.preventDefault();
        nb_handleEditorTab(event, editor);
        return;
    }

    // 2. Enter：自适应缩进
    if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        nb_handleEditorEnter(editor);
        return;
    }

    // 3. 配对字符：自动包裹选中文本（支持 " ' ` ( ) [ ] { }）
    const PAIR_CHARS = {
        '"': '"', "'": "'", '`': '`',
        '(': ')', ')': '(',
        '[': ']', ']': '[',
        '{': '}', '}': '{'
    };
    if (PAIR_CHARS[event.key] && !event.isComposing) {
        event.preventDefault();
        nb_handleEditorPairChar(event, editor, PAIR_CHARS[event.key]);
        return;
    }
}

/**
 * 处理Tab/Shift+Tab缩进（完全兼容原生撤销栈）
 * @param {KeyboardEvent} event - 键盘事件对象
 * @param {HTMLTextAreaElement} editor - textarea DOM实例
 */
function nb_handleEditorTab(event, editor) {
    const INDENT = '    '; // 默认4空格，后续可加FM配置控制
    const { start, end } = nb_getEditorSelection(editor);
    const content = editor.value;

    // ---------- 无选中文本：处理当前行缩进 ----------
    if (start === end) {
        if (event.shiftKey) {
            // Shift+Tab：删除当前行左侧的缩进（最多删4个，不足则全删）
            const beforeCursor = content.slice(0, start);
            const lineStart = beforeCursor.lastIndexOf('\n') + 1;
            const currentLine = content.slice(lineStart, start);
            const indentMatch = currentLine.match(/^(\s*)/);
            const currentIndent = indentMatch ? indentMatch[1] : '';
            const deleteLen = Math.min(INDENT.length, currentIndent.length);
            if (deleteLen > 0) {
                // 1. 选中要删除的缩进内容
                editor.setSelectionRange(lineStart, lineStart + deleteLen);
                // 2. 执行删除命令，浏览器自动记录到撤销栈
                document.execCommand('delete', false);
            }
        } else {
            // Tab：插入4空格，浏览器自动记录到撤销栈
            document.execCommand('insertText', false, INDENT);
        }
        return;
    }

    // ---------- 有选中文本：按行处理缩进 ----------
    const selected = content.slice(start, end);
    const selectedLines = selected.split('\n');
    let newSelected;

    if (event.shiftKey) {
        // Shift+Tab：减少每行缩进（最多删4个，不足则全删，无缩进的行不变）
        newSelected = selectedLines.map(line => {
            const indentMatch = line.match(/^(\s*)/);
            const lineIndent = indentMatch ? indentMatch[1] : '';
            const deleteLen = Math.min(INDENT.length, lineIndent.length);
            return deleteLen > 0 ? line.slice(deleteLen) : line;
        }).join('\n');
    } else {
        // Tab：给每行加4空格
        newSelected = selectedLines.map(line => INDENT + line).join('\n');
    }

    // 1. 选中原来的内容
    editor.setSelectionRange(start, end);
    // 2. 替换选中内容，浏览器自动记录到撤销栈
    document.execCommand('insertText', false, newSelected);
}

/**
 * 处理Enter自适应缩进（完全兼容原生撤销栈）
 * @param {HTMLTextAreaElement} editor - textarea DOM实例
 */
function nb_handleEditorEnter(editor) {
    const LINE_BREAK = '\n';
    const { start } = nb_getEditorSelection(editor);
    const content = editor.value;

    // 获取当前行的缩进（行首到光标前的所有空格）
    const beforeCursor = content.slice(0, start);
    const lineStart = beforeCursor.lastIndexOf(LINE_BREAK) + 1;
    const currentLine = content.slice(lineStart, start);
    const indentMatch = currentLine.match(/^(\s*)/);
    const indent = indentMatch ? indentMatch[1] : '';

    // 插入换行+缩进，浏览器自动记录到撤销栈
    document.execCommand('insertText', false, LINE_BREAK + indent);
}

/**
 * 处理配对字符自动包裹（完全兼容原生撤销栈）
 * @param {KeyboardEvent} event - 键盘事件对象
 * @param {HTMLTextAreaElement} editor - textarea DOM实例
 * @param {string} closeChar - 对应的闭合字符
 */
function nb_handleEditorPairChar(event, editor, closeChar) {
    const openChar = event.key;
    const { start, end } = nb_getEditorSelection(editor);

    if (start === end) {
        // 无选中文本：插入配对字符，光标停在中间
        document.execCommand('insertText', false, openChar + closeChar);
        // 移动光标到两个字符中间（仅移动光标，不修改内容，不影响撤销栈）
        editor.setSelectionRange(start + 1, start + 1);
    } else {
        // 有选中文本：包裹选中内容，光标停在末尾
        const selectedText = editor.value.slice(start, end);
        document.execCommand('insertText', false, openChar + selectedText + closeChar);
    }
}