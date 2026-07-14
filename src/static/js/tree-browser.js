document.addEventListener('alpine:init', () => {
    Alpine.data('treeBrowser', () => ({
        selectedFileNode: null,
        focusedNodeId: null,
        contextMenu: { show: false, x: 0, y: 0, targetNode: null, items: [] },

        rootNode: {
            id: '#',
            type: 'dir',
            text: '我的笔记本',
            expanded: true,
            loading: false,
            loaded: false,
            children: []
        },
        // ===== Drag & Drop =====
        dragging: false,
        dragNode: null,          // 正在拖拽的节点
        dragGhost: null,         // 拖拽时的幽灵 DOM
        dragHoverNodeId: null,   // hover 高亮的目录 ID
        dragStartX: 0,           // 记录按下时的X坐标
        dragStartY: 0,           // 记录按下时的Y坐标
        _dragMoveHandler: null,
        _dragUpHandler: null,

        init() {
            this.loadChildren(this.rootNode).then(() => {
                this.restoreLastPathOnStartup().then(r => {});
            });

            // ✅ 监听选中节点的变化，记录 localStorage，以便刷新页面之后，可以重新载入
            this.$watch('selectedFileNode', () => {
                if (this.selectedFileNode && this.selectedFileNode.id) {
                    localStorage.setItem('notebook_last_path', this.selectedFileNode.id);
                } else {
                    localStorage.removeItem('notebook_last_path');
                }
            }, { deep: true }); // deep: true 才能监听到selectedFileNode.id的变化

            // 监听主页面关闭文件事件，取消目录树中选中的高亮
            window.addEventListener('notebook:closeFile', () => {
                this.selectedFileNode = null;
            });
            window.addEventListener('notebook:closeAllPopups', () => {
                this.closeContextMenu();
            });
            // 页面卸载时清理拖拽事件
            window.addEventListener('beforeunload', () => {
                if (this.dragging) {
                    window.removeEventListener('mousemove', this._dragMoveHandler);
                    window.removeEventListener('mouseup', this._dragUpHandler);
                    if (this.dragGhost) {
                        document.body.removeChild(this.dragGhost);
                    }
                }
            });
        },

        // ============================
        // [Node] 节点操作方法
        // ============================
        sortNodes(nodes) {
            nodes.sort((a, b) => {
                const aIsDir = isDirType(a.type);
                const bIsDir = isDirType(b.type);
                if (aIsDir && !bIsDir) return -1;
                if (!aIsDir && bIsDir) return 1;
                return a.text.localeCompare(b.text, 'zh-CN');
            });
        },
        findNode(id, nodes = this.rootNode.children) {
            for (const node of nodes) {
                if (node.id === id) return node;
                if (node.children && node.children.length > 0) {
                    const found = this.findNode(id, node.children);
                    if (found) return found;
                }
            }
            return null;
        },
        findParent(id, nodes = this.rootNode.children, parent = null) {
            for (const node of nodes) {
                if (node.id === id) return parent;
                if (node.children && node.children.length > 0) {
                    const found = this.findParent(id, node.children, node);
                    if (found) return found;
                }
            }
            return null;
        },
        generateNodeHtml(node, depth = 0) {
            const isDir = isDirType(node.type);
            const indent = depth * 14 + 10;
            const isSelected = this.selectedFileNode?.id === node.id;
            const isFocused = this.focusedNodeId === node.id && !isSelected;
            const isDragHover = this.dragHoverNodeId === node.id;

            let iconClass = 'fas fa-file text-gray-400';
            if (isDir) {
                iconClass = node.expanded ? 'fas fa-folder-open text-amber-400' : 'fas fa-folder text-amber-500';
            } else if (isMarkdownType(node.text)) {
                iconClass = 'fas fa-file-alt text-blue-400';
            } else if (isImageType(node.text)) {
                iconClass = 'fas fa-file-image text-pink-400';
            } else if (/\.(js|ts|py|java|cpp|go|rs|json|xml|yaml|yml|css|html)$/i.test(node.text)) {
                iconClass = 'fas fa-file-code text-green-500';
            }

            let rowClass = 'group flex items-center px-1 py-1 cursor-pointer rounded-md transition-colors ';
            if (isSelected) {
                rowClass += 'bg-blue-50 text-blue-600 font-medium ';
            } else {
                rowClass += 'text-gray-700 ';

                if (this.dragging && this.dragNode?.id === node.id) {
                    rowClass += 'bg-blue-300 ';
                }
                if (isDragHover) {
                    rowClass += 'bg-blue-300 hover:none ';
                }else if (isFocused) {
                    rowClass += 'bg-gray-100 hover:bg-gray-200 '
                } else {
                    rowClass += 'hover:bg-gray-100 ';
                }
            }
            rowClass = rowClass.replace(/\s+/g, ' ').trim();

            let html = `<div
                    class="${rowClass} select-none"
                    data-node-id="${node.id}"
                    data-node-type="${node.type}"
                    style="padding-left: ${indent}px; padding-right: 12px; width: max-content; min-width: 100%;"
                    @mousedown="startDrag($event, '${node.id}')"
                >`;

            if (isDir) {
                html += `<button class="mr-1.5 text-gray-300 group-hover:text-gray-500 transition-transform duration-200 flex-shrink-0 w-3 h-3 flex items-center justify-center ${node.expanded ? 'rotate-90 text-blue-400' : ''}" data-action="toggle"><i class="fas fa-chevron-right text-[10px]"></i></button>`;
            } else {
                html += `<div class="w-3 mr-1.5 flex-shrink-0"></div>`;
            }

            if (node.loading) {
                html += `<div class="mr-2 flex-shrink-0"><div class="loading-spinner"></div></div>`;
            } else {
                html += `<i class="${iconClass} mr-2 text-sm w-4 text-center flex-shrink-0"></i>`;
            }

            html += `<span class="truncate flex-1 text-sm">${escapeHtml(node.text)}</span></div>`;

            if (isDir && node.expanded) {
                html += `<div class="node-children">`;
                if (node.loading) {
                    html += `<div style="padding-left: ${indent + 14}px;" class="py-1.5 text-xs text-gray-400">加载中...</div>`;
                } else if (node.children?.length) {
                    node.children.forEach(child => {
                        html += this.generateNodeHtml(child, depth + 1);
                    });
                }
                html += `</div>`;
            }

            return html;
        },
        get treeHtml() {
            if (!this.rootNode.children) return '';
            return this.rootNode.children.map(child => this.generateNodeHtml(child, 0)).join('');
        },
        async loadChildren(node) {
            node.loading = true;
            try {
                const response = await fetch('/notebook/listdir', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: node.id }),
                    credentials: 'include',
                });
                const resp = await response.json();
                if (resp.code !== 0) {
                    this.showToast(resp.msg || '加载失败', 'error');
                    return;
                }
                node.children = resp.data.map(item => ({
                    id: item.id,
                    type: item.type || 'file',
                    text: item.text || '',
                    expanded: false,
                    loading: false,
                    loaded: false,
                    children: []
                }));
                this.sortNodes(node.children);
                node.loaded = true;
                node.expanded = true;
            } catch (error) {
                this.showToast('加载目录失败', 'error');
            } finally {
                node.loading = false;
            }
        },
        async toggleNode(node) {
            if (!isDirType(node.type)) return;
            if (!node.loaded) { return await this.loadChildren(node); }
            node.expanded = !node.expanded;
        },
        async restoreLastPathOnStartup() {
            const path = localStorage.getItem('notebook_last_path');
            if (!path) return;

            // 确保虚拟根已加载（后端返回真正的根节点 "/"）
            if (!this.rootNode.loaded) {
                await this.loadChildren(this.rootNode);
            }

            // 找到真正的根节点（id 为 "/"）
            const realRoot = this.rootNode.children.find(c => c.id === '/');
            if (!realRoot) {
                this.showToast('目录加载失败！', 'error');
                localStorage.removeItem('notebook_last_path');
                return;
            }

            // 把 path 拆成段：
            // - '/test.md' → ['test.md']
            // - '/notes/drafts/idea.md' → ['notes', 'drafts', 'idea.md']
            const segments = path.split('/').filter(p => p);
            let parent = realRoot;
            let currentId = '/'; // 从真正的根开始

            for (let i = 0; i < segments.length; i++) {
                const segment = segments[i];

                // 构建要查找的完整 id（和后端返回的 id 格式一致）
                if (currentId === '/') {
                    currentId = '/' + segment; // '/test.md'
                } else {
                    currentId = currentId + '/' + segment; // '/notes' + '/drafts' = '/notes/drafts'
                }

                // 确保父目录已加载
                if (!parent.loaded) {
                    await this.loadChildren(parent);
                }

                const found = parent.children.find(c => c.id === currentId);
                if (!found) {
                    this.showToast('恢复上次编辑位置失败，文件可能已被移动或删除', 'error');
                    localStorage.removeItem('notebook_last_path');
                    return;
                }

                if (i < segments.length - 1) {
                    // 不是最后一段 → 是目录，展开继续深入
                    found.expanded = true;
                    parent = found;
                    continue;
                }

                if (isDirType(found.type)) {
                    // 不应该触发到这里
                    this.showToast('目录不支持打开', 'error');
                    localStorage.removeItem('notebook_last_path');
                }

                // 记录，并滚动到可视区域
                this.selectedFileNode = { ...found };
                this.$nextTick(() => {
                    const el = document.querySelector(`[data-node-id="${found.id}"]`);
                    if (el) el.scrollIntoView({ block: 'nearest' });
                });

                // 通知主页面打开文件
                this.notebook__openFile(found.id).then(r => {})
            }
        },
        // ============================
        // [DRAG & DROP] 拖拽核心逻辑
        // ============================
        startDrag(event, nodeId) {
            if (event.button !== 0) return;
            const node = this.findNode(nodeId);
            if (!node) return;

            // ✅ 只记录初始位置，不立即进入拖拽、不阻止默认事件
            this.dragStartX = event.clientX;
            this.dragStartY = event.clientY;
            this.dragNode = node;

            this._dragMoveHandler = this.handleDragMove.bind(this);
            this._dragUpHandler = this.handleDragEnd.bind(this);
            window.addEventListener('mousemove', this._dragMoveHandler);
            window.addEventListener('mouseup', this._dragUpHandler);
        },
        handleDragMove(event) {
            if (!this.dragNode) return;

            // ✅ 关键：移动超过5px才判定为「拖拽」，否则还是「点击」
            const deltaX = Math.abs(event.clientX - this.dragStartX);
            const deltaY = Math.abs(event.clientY - this.dragStartY);
            const DRAG_THRESHOLD = 5; // 阈值，可调整

            // 还没进入拖拽状态，且移动距离够了
            if (!this.dragging) {
                // 还未进入 dragging 状态，判断距离
                if (deltaX <= DRAG_THRESHOLD && deltaY <= DRAG_THRESHOLD) {
                    // 距离不够，直接返回，要么等待抬起，要么等待继续移动
                    return;
                }
                // 距离够了，进入 dragging 逻辑
                this.dragging = true;
                // 阻止默认行为（比如选中文本），不影响点击
                event.preventDefault();

                // 创建幽灵节点，在这里只会执行一次，下一次就是 dragging === true
                this.dragGhost = document.createElement('div');
                this.dragGhost.className = `
                        fixed z-[100]
                        px-3 py-1.5
                        bg-white
                        text-gray-800
                        text-sm
                        rounded-lg
                        shadow-xl
                        ring-1 ring-gray-200
                        pointer-events-none
                        select-none
                        opacity-95
                    `.replace(/\s+/g, ' ');
                this.dragGhost.textContent = '移动：' + this.dragNode.text;
                document.body.appendChild(this.dragGhost);
            }
            // 到达这里，已经进入到了 draging 状态，并且已经创建好了幽灵节点，判断是否悬停在某个node
            this.dragGhost.style.left = event.clientX + 10 + 'px';
            this.dragGhost.style.top = event.clientY + 10 + 'px';
            const el = document.elementFromPoint(event.clientX, event.clientY);
            const nodeEl = el?.closest('[data-node-id]');
            if (!nodeEl) {
                this.dragHoverNodeId = null;
                return;
            }

            const nodeId = nodeEl.dataset.nodeId;
            const node = this.findNode(nodeId);
            this.dragHoverNodeId = node ? nodeId : null;
        },
        handleDragEnd() {
            window.removeEventListener('mousemove', this._dragMoveHandler);
            window.removeEventListener('mouseup', this._dragUpHandler);
            this.dragStartX = 0;
            this.dragStartY = 0;
            if (!this.dragging) {
                // 没有经过dragMove，直接进入到了DragEnd (鼠标按下后直接抬起，没有移动)
                return;
            }
            // 已产生拖拽事件，重置状态
            this.dragging = false;

            // 移除幽灵节点
            if (this.dragGhost) {
                document.body.removeChild(this.dragGhost);
                this.dragGhost = null;
            }
            // 判断最终停留的节点
            const dstNode = this.dragHoverNodeId ? this.findNode(this.dragHoverNodeId) : null;
            this.dragHoverNodeId = null;

            if (dstNode && this.dragNode) {
                this.tryMoveNode(this.dragNode, dstNode).then(r => {});
            }
            this.dragNode = null;
        },
        async tryMoveNode(srcNode, dstNode) {
            if (srcNode.id === dstNode.id) {
                // 拖放到自身了，不提示
                return;
            }
            if (dstNode.id.startsWith(srcNode.id + '/')){
                this.showToast('不能移动到子目录', 'error');
                return;
            }
            if (!isDirType(dstNode.type)) {
                this.showToast('目标必须是目录', 'error');
                return;
            }
            const dstParent = this.findNode(dstNode.id);
            if (dstParent?.children?.some(c => c.text === srcNode.text)) {
                this.showToast('目标目录已存在同名文件或目录', 'error');
                return;
            }

            // 检查OK，给予提示
            const confirmed = await this.showConfirm({
                title: isDirType(srcNode.type) ? '移动目录' : '移动文件',
                message: `是否将 "${srcNode.text}" 移动到 "${dstNode.text}"？`,
                confirmText: '移动',
                cancelText: '取消',
                type: 'info'
            });
            if (!confirmed) return;

            // 开始移动
            this.showOverlay('正在移动...');
            try {
                // ✅ 模拟后端请求（替换为你真实的 fetch）
                await new Promise(r => setTimeout(r, 800));

                const resp = await fetch('/notebook/mv', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        src: srcNode.id,
                        dst: dstNode.id
                    }),
                    credentials: 'include'
                });
                const data = await resp.json();
                if (data.code !== 0) {
                    throw new Error(data.msg || '移动失败');
                }
                this.applyMoveToTree(srcNode, dstNode);
                this.showToast('移动成功', 'success');
            } catch (e) {
                this.showToast(e.message || '移动失败', 'error');
            } finally {
                this.hideOverlay();
            }
        },
        _updateNodePathRecursive (node, oldPath, newPath) {
            // 递归替换每个 node 的父目录，对于 oldPath 和 newPath 的准确性，需要调用方保证
            // 适用场景
            // - 移动某个子树，移动后，父目录改变，eg:
            //      /a/b/c... 把 b 移动到 /new_path/x 之后
            //      变成: /new_path/x/b/c...
            //      此时对于每个 node, 相当于将 /a/ 替换为 /new_path/x/
            // - 重命名某个子树，同理
            node.id = node.id.replace(oldPath, newPath);
            if (node.children?.length) {
                node.children.forEach(child =>
                    this._updateNodePathRecursive(child, oldPath, newPath)
                );
            }
        },
        applyMoveToTree(srcNode, dstNode) {
            // 1. 处理原节点，将原节点从原父节点的孩子中移除
            const srcParent = this.findParent(srcNode.id);
            if (srcParent) {
                srcParent.children = srcParent.children.filter(c => c.id !== srcNode.id);
            }

            // 2. 处理目标节点，将原来的 node 插入到新目录
            // 如果目标目录本身就未加载，则不管（下次展开之时自然会更新），加载的情况下，需要把 src 添加进去
            if (dstNode.loaded) {
                if (!dstNode.children) dstNode.children = [];
                dstNode.children.push(srcNode);
                this.sortNodes(dstNode.children);
                dstNode.expanded = true;
            }

            // 3. 更新srcNode移动过去之后，它自己和所有孩子的路径
            const originSrcID = srcNode.id;
            const newId = rStripSlash(dstNode.id) + '/' + srcNode.text;
            this._updateNodePathRecursive(srcNode, srcNode.id, newId);

            // 移动当前打开文档自己、父节点时，
            // 需要修改当前选中的节点，并同步修改主页文件的路径
            let newFilepath = '';
            if (this.selectedFileNode?.id === originSrcID) {
                // 移动自己
                newFilepath = rStripSlash(dstNode.id) + '/' + this.selectedFileNode.text;
            } else if (this.selectedFileNode?.id.startsWith(originSrcID + '/')) {
                // 找到 this.selectedFileNode.id 到 originSrcID 的相对路径，挂到 srcNode 移动之后的路径即可
                const relPath = lStripSlash(this.selectedFileNode.id.replace(originSrcID, ''));
                newFilepath = rStripSlash(newId) + '/' + relPath;
            } else {
                return;
            }

            // 由于懒加载特性，dstNode 未必已加载，所以移动之后的 srcNode 未必存在
            const findFileNode = this.findNode(newFilepath)
            if (findFileNode) {
                if(isDirType(findFileNode.type)) {
                    // 正常不会走到这里，但加保护
                    this.showToast('目录错误，请刷新页面', 'error');
                    return;
                }
                this.selectedFileNode = { ...findFileNode };
            } else {
                this.selectedFileNode = { id: newFilepath, type: 'file', text: getFilename(newFilepath), expanded: true, loading: false, loaded: true, children: [] }
            }
            this.notebook__changeFilePath(this.selectedFileNode.id);
        },
        // ============================
        // 树的交互、操作
        // ============================
        async onTreeClick(event) {
            if (this.dragging) return;
            if (this.contextMenu.show) { this.closeContextMenu(); return; }

            const target = event.target.closest('[data-node-id]');
            if (!target) return;
            const id = target.dataset.nodeId;
            const type = target.dataset.nodeType;
            const node = this.findNode(id);
            if (!node) return;

            if (event.target.closest('[data-action="toggle"]')) {
                await this.toggleNode(node);
                return;
            }
            if (isDirType(type)) {
                // 只展开/折叠，不碰 selectedNodeId（它会由 currentFile 驱动）
                await this.toggleNode(node);
                this.focusedNodeId = id;
                return;
            }

            if (this.notebook__hasUnSavedChanges()) {
                const confirmed = await this.showConfirm({
                    title: '未保存的更改',
                    message: '当前编辑内容尚未保存，打开其他文件将丢失未保存的更改。确定要继续吗？',
                    confirmText: '放弃更改',
                    cancelText: '取消',
                    type: 'warning'
                })
                if (!confirmed) return;
            }

            this.focusedNodeId = id;
            this.selectedFileNode = { ...node };
            await this.notebook__openFile(node.id);
        },
        onTreeRightClick(event) {
            if (this.dragging) return;
            const target = event.target.closest('[data-node-id]');
            if (!target) return;
            const id = target.dataset.nodeId;
            const type = target.dataset.nodeType;
            const nodeData = this.findNode(id);
            if (nodeData) {
                this.focusedNodeId = id;
                this.showContextMenu(event, { id, type, name: nodeData.text });
            }
        },
        showContextMenu(event, node) {
            const { id, type, name } = node;
            const dir = isDirType(type);
            const md = isMarkdownType(name);
            const img = isImageType(name);

            let items = [];
            if (dir) {
                items.push({ label: '📂 新建目录', action: 'mkdir' });
                items.push({ label: '📄 新建文件', action: 'newfile' });
                items.push({ label: '⬆️ 上传文件', action: 'upload' });
                items.push({ divider: true });
                if (node.id === '/') {
                    items.push({ label: '🚀 生成站点', action: 'publish' });
                } else {
                    items.push({ label: '✏️ 重命名', action: 'rename' });
                    items.push({ label: '🗑️ 删除', action: 'delete', danger: true });
                }
            } else {
                if (md) items.push({ label: '📝 打开编辑', action: 'open' });
                if (img) items.push({ label: '🖼️ 预览图片', action: 'open' });
                items.push({ label: '✏️ 重命名', action: 'rename' });
                items.push({ label: '🔗 分享', action: 'share' });
                items.push({ divider: true });
                items.push({ label: '🗑️ 删除', action: 'delete', danger: true });
            }

            this.contextMenu = { show: true, x: event.clientX, y: event.clientY, targetNode: node, items };
        },
        closeContextMenu() { this.contextMenu.show = false; },
        async executeContextAction(action) {
            const node = this.contextMenu.targetNode;
            this.contextMenu.show = false;
            switch (action) {
                case 'open':     await this.ctxOpenFile(node); break;
                case 'mkdir':    await this.ctxMkdir(node);    break;
                case 'newfile':  await this.ctxNewFile(node);  break;
                case 'upload':   this.ctxUpload(node);         break;
                case 'rename':   await this.ctxRename(node);   break;
                case 'delete':   await this.ctxDelete(node);   break;
                case 'share':    await this.notebook__openSharePage(node.id); break;
                case 'publish':  await this.notebook__publishBlog(node.id); break;
            }
        },
        async ctxOpenFile(node) {
            const confirmed = await this.notebook__ensureDiscardUnSavedContent();
            if (!confirmed) return;
            await this.notebook__openFile(node.id);
        },
        _buildChildNodeID(nodeID, name) {
            // 安全地把 name 拼接到 nodeID 后面，构建孩子的 path
            return nodeID.endsWith('/') ? nodeID + name : nodeID + '/' + name;
        },
        async ctxMkdir(mockNode) {
            const node = this.findNode(mockNode.id)
            if (!node) { this.showToast('未能获取到节点，请刷新页面'); return; }
            const name = await this.showPrompt({
                title: '新建目录',
                message: '请输入新目录名称：',
                placeholder: '目录名称',
                icon: 'fas fa-folder-plus'
            });
            if (!name) return;
            if (name.includes('/') || name.includes('\\')) return this.showToast('名称不能包含 / 或 \\', 'error');
            try {
                const res = await fetch('/notebook/mkdir', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: node.id, dir_name: name }),
                    credentials: 'include',
                });
                const data = await res.json();
                if (data.code !== 0) {
                    this.showToast(data.msg || '创建失败', 'error');
                    return;
                }
            } catch (e) { this.showToast('创建失败', 'error'); return; }

            this.showToast('目录创建成功', 'success');

            // 如果该节点没有被加载，就跳过。下一次点击会自动加载出来。否则追加到孩子里
            if (!node.loaded) return;

            // 如果已经存在，则重置状态。正常情况不会触发到这里
            const existing = node.children.find(c => c.text === name);
            if (existing) {
                existing.type = 'dir';
                existing.children = null;
                existing.loaded = false
                return;
            }
            node.children.push({
                id: this._buildChildNodeID(node.id, name),
                type: 'dir',
                text: name,
                expanded: false,
                loading: false,
                loaded: false,
                children: null
            });
            this.sortNodes(node.children);
            node.expanded = true;
        },
        async ctxNewFile(mockNode) {
            const node = this.findNode(mockNode.id)
            if (!node) { this.showToast('未能获取到节点，请刷新页面'); return; }
            const name = await this.showPrompt({
                title: '新建文件',
                message: '请输入新文件名称：',
                placeholder: '文件名（如：note.md）',
                icon: 'fas fa-file-circle-plus'
            });
            if (!name) return;
            if (name.includes('/') || name.includes('\\')) return this.showToast('名称不能包含 / 或 \\', 'error');

            try {
                const res = await fetch('/notebook/new', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: node.id, file_name: name }),
                    credentials: 'include',
                });
                const data = await res.json();
                if (data.code !== 0) {
                    this.showToast('文件创建失败！', 'error');
                    return;
                }
            } catch (e) { this.showToast('创建失败', 'error'); return; }

            this.showToast('文件创建成功', 'success');
            if (!node.loaded) return;

            const existing = node.children.find(c => c.text === name);
            if (existing) { existing.type = 'file'; return; }

            node.children.push({
                id: this._buildChildNodeID(node.id, name),
                type: 'file',
                text: name,
                expanded: false,
                loading: false,
                loaded: false,
                children: null
            });
            this.sortNodes(node.children);
            node.expanded = true;
        },
        ctxUpload(mockNode) {
            const input = document.createElement('input');
            input.type = 'file'; input.multiple = true;
            input.onchange = async () => {
                const node = this.findNode(mockNode.id);
                if (!node) { this.showToast('未能获取到节点，请刷新页面'); return; }
                for (const file of input.files) {
                    if (file.size > 5 * 1024 * 1024) { this.showToast(`${file.name} 超过5MB`, 'error'); continue; }
                    const formData = new FormData();
                    formData.append('file', file); formData.append('node_id', node.id);
                    try {
                        await fetch('/notebook/upload', { method: 'POST', body: formData, credentials: 'include' });
                        const existing = node.children.find(c => c.text === file.name);
                        if (existing) {
                            existing.type = 'file';
                            continue;
                        }
                        if (!node.loaded) continue;
                        node.children.push({
                            id: this._buildChildNodeID(node.id, file.name),
                            type: 'file',
                            text: file.name,
                            expanded: false,
                            loading: false,
                            loaded: false,
                            children: null
                        });
                    } catch (e) {
                        this.showToast(`上传 ${file.name} 失败`, 'error');
                    }
                }
                if (node.loaded) {
                    this.sortNodes(node.children);
                    node.expanded = true;
                }
                this.showToast('上传完成', 'success');
            };
            input.click();
        },
        async ctxRename(mockNode) {
            const node = this.findNode(mockNode.id);
            if (!node) { this.showToast('未能获取到节点，请刷新页面'); return; }
            const oldPath = node.id;
            const newName = await this.showPrompt({
                title: '重命名',
                message: '请输入新名称：',
                placeholder: '新名称',
                defaultValue: node.text,
                icon: 'fas fa-i-cursor'
            });
            if (!newName || newName === node.text) return;
            if (newName.includes('/') || newName.includes('\\')) {
                this.showToast('名称不能包含 / 或 \\', 'error');
                return;
            }
            // 如果文件已打开，禁止修改扩展名
            if (this.selectedFileNode?.id === node.id && !isSameExt(newName, node.id)) {
                this.showToast('该文件正在被编辑，禁止修改扩展名', 'error');
                return;
            }
            try {
                const res = await fetch('/notebook/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: oldPath, new_name: newName }),
                    credentials: 'include'
                });
                const data = await res.json();
                if (data.code !== 0) {
                    this.showToast(data.msg ? '操作失败：' + data.msg : '操作失败，请重试', 'error');
                    return;
                }
            } catch (e) {
                this.showToast('重命名失败', 'error');
            }

            this.showToast('重命名成功', 'success');
            // 重名成功，需要修改树结构，包括
            // - 如果修改的原节点是目录，对自己做重命名，并同步修改孩子的路径，判断修改的原节点是否为当前文档的父亲
            //    - 不是，退出
            //    - 是，同步修改 this.selectedFileNode，并通知 notebook 修改当前打开文件的路径
            // - 如果修改的原节点是文件，对自己做重命名，并判断原节点是否就是选中的节点 this.selectedFileNode
            //    - 不是选中的节点，退出
            //    - 是选中的节点，同步修改 this.selectedFileNode, 通知 notebook 修改当前打开文件的路径
            const oldNode = node;
            const parent = this.findParent(oldNode.id);
            const newPath = this._buildChildNodeID(parent.id, newName);

            // 对自己做重命名
            const newNode = oldNode;
            newNode.id = newPath;
            newNode.text = newName;
            if (parent) this.sortNodes(parent.children);

            if (isDirType(oldNode.type)) {
                // 文件夹类型
                if (!newNode.loaded) return; // 未加载，说明它肯定不是当前文档的父亲，也没有孩子需要处理，直接退出即可

                // 递归修改孩子的父路径
                // 调用这个方法，会重复尝试将 newNode 的 id 由旧路径改为新路径，但没有副作用
                this._updateNodePathRecursive(newNode, oldPath, newPath);

                // 判断原节点是否为当前文档的父亲，若是，则修改当前文档的父路径
                if (this.selectedFileNode?.id.startsWith(oldPath + '/')) {
                    // 说明此时，oldNode 是老父亲，newNode 是新父亲，直接 replace 即可
                    const newSelectFilePath = this.selectedFileNode.id.replace(oldPath, newPath);
                    const newSelNode = this.findNode(newSelectFilePath);
                    if (!newSelNode) {
                        // 正常情况不会进入到这里，但加保护
                        this.showToast('文档路径错误，请刷新页面', 'error');
                        return;
                    }
                    this.selectedFileNode = { ...newSelNode }
                    this.notebook__changeFilePath(newSelNode.id);
                }
            } else {
                // oldNode 是文件
                if (this.selectedFileNode.id === oldPath ) {
                    this.selectedFileNode = { ...newNode };
                    this.notebook__changeFilePath(newNode.id);
                }
            }
        },
        async ctxDelete(mockNode) {
            const node = this.findNode(mockNode.id);
            if (!node) { this.showToast('未能获取到节点，请刷新页面'); return; }

            const confirmed = await this.showConfirm({
                title: '删除确认', message: `确定要删除 "${node.text}" 吗？此操作不可恢复。`, confirmText: '确认删除', type: 'danger' });
            if (!confirmed) return;

            // 记录父亲
            const parent = this.findParent(node.id);

            try {
                const res = await fetch('/notebook/rm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: node.id }),
                    credentials: 'include',
                });
                const data = await res.json();
                if (data.code !== 0) {
                    this.showToast(data.msg || '删除失败', 'error');
                    return;
                }
            } catch (e) {
                this.showToast('删除失败', 'error');
                return;
            }
            // 由于根节点不允许删除，所以 parent 必然存在
            parent.children = parent.children.filter(c => c.id !== node.id);

            // 清除掉焦点
            if (this.focusedNodeId === node.id) {
                this.focusedNodeId = null;
            }
            // 如果清除的是当前文档，或者是当前文档的父亲，关闭文档
            if (this.selectedFileNode?.id === node.id || this.selectedFileNode?.id?.startsWith(node.id + '/')) {
                this.selectedFileNode = null;
                this.notebook__closeFile();
            }
            this.showToast(`成功删除对象: ${node.text}`, 'info');
        },
    }));
});
