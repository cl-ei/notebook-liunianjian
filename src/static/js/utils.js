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
function isTextType(filepath) {
    if (!filepath) return false;
    return /\.(md|markdown|txt|text|html|htm|xml|json|yaml|yml|ini|conf|sh|bash|js|ts|py|go|java|c|cpp|rs|css|scss|less)$/i.test(filepath);
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
        // 校验是否包含多个冒号（允许值里有冒号，比如date里的:，但键里不能有）
        if (trimmed.indexOf(':', colonIdx + 1) !== -1 && !trimmed.startsWith('date:')) {
            // 排除date字段的正常冒号
            const keyPart = trimmed.slice(0, colonIdx);
            const valPart = trimmed.slice(colonIdx + 1);
            if (valPart.split(':').length - 1 > 1) {
                return {
                    status: -1,
                    log: `第${parseLine}行：键值对包含多余冒号，仅允许值中存在单个冒号（如date字段）`,
                    content
                };
            }
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
    console.log("fmResult: ", fmResult);

    const rawHtml = marked.parse(fmResult.content, { renderer });
    console.log("rawHtml: ", rawHtml);

    const html = DOMPurify.sanitize(rawHtml, {
        ADD_TAGS: ['img'],
        ADD_ATTR: ['src', 'alt', 'title', 'loading', 'style', 'onerror'], // 必须加 onerror
        FORBID_TAGS: ['script', 'style', 'link', 'meta'],
        FORBID_ATTR: ['onload', 'onclick', 'onmouseover'] // 只禁止不需要的事件
    });

    return {status: fmResult.status, log: fmResult.log, html: html}
}
