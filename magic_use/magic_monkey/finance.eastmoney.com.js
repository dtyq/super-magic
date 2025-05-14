// ==UserScript==
// @name         麦吉 东方财富财经 超净化
// @namespace    https://dtyq.com/
// @version      1.6
// @description  清理东方财富财经网站页面，聚焦文章内容和标题，移除干扰元素。自动关闭特定弹窗。
// @author       Gemini & DTYQ
// @match        *://finance.eastmoney.com/a/*
// @grant        none
// ==/UserScript==

(function() {
  'use strict';

  // --- 1. 定位核心元素 ---
  let titleElement = document.querySelector('#topbox'); // 定位标题区域
  let mainContentContainer = document.querySelector('div.mainleft'); // **新增：优先定位 .mainleft**
  let contentElement = null; // 稍后在 mainContentContainer 中查找具体内容元素

  // 如果连 .mainleft 都找不到，则尝试原来的策略寻找内容元素
  if (!mainContentContainer) {
      console.warn('麦吉净化脚本：未能找到 .mainleft 容器，尝试查找内部内容元素...');
      contentElement = document.querySelector('div.newsContent') ||
                         document.querySelector('div.article_body') ||
                         document.querySelector('#ContentBody');
  } else {
      // 如果找到了 .mainleft，就在它内部查找具体的内容元素（可选，主要为了样式）
      contentElement = mainContentContainer.querySelector('div.newsContent') ||
                         mainContentContainer.querySelector('div.article_body') ||
                         mainContentContainer.querySelector('#ContentBody') ||
                         mainContentContainer; // 如果内部找不到特定元素，则将 .mainleft 自身作为内容元素
  }

  // 确定主要的样式目标 (优先 .mainleft)
  const primaryContentTarget = mainContentContainer || contentElement;

  // 如果找不到任何形式的内容区域，则退出
  if (!primaryContentTarget) {
    console.error('麦吉净化脚本：未能找到任何目标内容元素 (finance.eastmoney.com)。');
    return;
  }
  // 如果找不到标题，也打印一个信息，但不退出
  if (!titleElement) {
      console.warn('麦吉净化脚本：未能找到标题元素 #topbox，将只保留文章内容。');
  }

  // --- 2. 定义保留规则 ---
  const shouldKeepVisible = (element) => {
    // 保留标题区域及其内部元素
    if (titleElement && (element === titleElement || titleElement.contains(element))) {
        return true;
    }
    // **修改：保留主要内容容器及其内部元素**
    if (primaryContentTarget && (element === primaryContentTarget || primaryContentTarget.contains(element))) {
        return true;
    }
    return false;
  };

  // --- 3. 遍历并收集需要隐藏的元素 ---
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_ELEMENT,
    null,
    false
  );

  const elementsToHide = [];
  let currentNode = walker.nextNode();
  while (currentNode) {
    // 排除脚本自身可能注入的元素（虽然本脚本没注入）
    if (currentNode.closest && currentNode.closest('[data-userscript-managed]')) {
        currentNode = walker.nextNode();
        continue;
    }

    // 如果当前节点不应保留，则添加到待隐藏列表
    if (!shouldKeepVisible(currentNode)) {
      elementsToHide.push(currentNode);
    }
    currentNode = walker.nextNode();
  }

  // --- 4. 统一执行隐藏 ---
  elementsToHide.forEach(element => {
    // 再次确认不隐藏 body 和 html
    if (element !== document.body && element !== document.documentElement) {
        element.style.setProperty('display', 'none', 'important'); // 使用 !important 提高优先级
        element.style.setProperty('visibility', 'hidden', 'important');
    }
  });

  // --- 5. 确保目标元素及其所有祖先可见 ---
  const ensureVisible = (targetElement) => {
      if (!targetElement) return; // 如果元素不存在则跳过
      let ancestor = targetElement;
      while (ancestor && ancestor !== document.documentElement) {
        ancestor.style.setProperty('display', '', ''); // 清除可能存在的 display:none
        ancestor.style.setProperty('visibility', 'visible', 'important'); // 强制可见

        // 恢复 body 和 html 的默认滚动行为
        if (ancestor === document.body || ancestor === document.documentElement) {
            ancestor.style.overflow = '';
        }
        ancestor = ancestor.parentElement;
      }
  };

  ensureVisible(titleElement); // 确保标题可见
  ensureVisible(primaryContentTarget); // **修改：确保主要内容容器可见**

  // 单独确保 html 元素可见 (合并到ensureVisible内部逻辑已处理大部分情况，这里再次确认)
  if (document.documentElement) {
      document.documentElement.style.setProperty('display', '', '');
      document.documentElement.style.setProperty('visibility', 'visible', 'important');
      document.documentElement.style.overflow = '';
  }


  // --- 6. 应用样式，美化并居中目标元素 ---

  // **新增：强制重置 body 的关键样式，防止干扰**
  document.body.style.setProperty('width', 'auto', 'important');
  document.body.style.setProperty('margin', '0', 'important');
  document.body.style.setProperty('position', 'relative', 'important'); // 重置可能存在的 absolute/fixed
  document.body.style.setProperty('float', 'none', 'important'); // 清除可能的 float

  // 应用我们期望的 body 样式作为 flex 容器
  const bodyStyle = {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      minHeight: '100vh',
      padding: '40px 10px',
      boxSizing: 'border-box',
      backgroundColor: '#f0f2f5'
  };
  // 使用 setProperty 应用样式，提高优先级
  for (const [key, value] of Object.entries(bodyStyle)) {
      // 将驼峰命名转换为 kebab-case
      const kebabKey = key.replace(/[A-Z]/g, match => `-${match.toLowerCase()}`);
      document.body.style.setProperty(kebabKey, value, 'important');
  }


  // 设置标题区域样式
  if (titleElement) {
      Object.assign(titleElement.style, {
        display: 'block',
        visibility: 'visible',
        width: '90%',
        maxWidth: '850px',
        margin: '0 0 20px 0',
        padding: '20px 30px',
        backgroundColor: 'white',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        border: '1px solid #e8e8e8',
        borderRadius: '5px',
        position: 'relative',
        float: 'none',
        left: '',
        top: '',
        zIndex: 'auto'
      });
  }

  // **修改：设置 .mainleft 或备用内容容器的样式**
  Object.assign(primaryContentTarget.style, {
    display: 'block',
    visibility: 'visible',
    width: '90%',
    maxWidth: '850px',
    margin: '0', // **修改：移除 margin: 0 auto，让 body 的 align-items 生效**
    padding: '30px 40px',
    backgroundColor: 'white',
    boxShadow: '0 4px 15px rgba(0,0,0,0.12)',
    border: '1px solid #e8e8e8',
    borderRadius: '5px',
    position: 'relative',
    float: 'none', // **新增：清除 float**
    left: '',
    top: '',
    transform: '',
    zIndex: 'auto',
    height: '',
    overflow: 'visible' // **修改：允许内容溢出容器（如果需要）或设为 auto**
  });

  // 如果 contentElement 是 .mainleft 内部的元素，可能需要重置其 margin/padding
  if (mainContentContainer && contentElement && contentElement !== mainContentContainer) {
      contentElement.style.margin = '0';
      contentElement.style.padding = '0';
  }

  console.log('麦吉 东方财富财经 超净化脚本 (v1.5) 样式应用完毕');

  // --- 7. 监听并自动关闭特定弹窗 ---
  // **修改：仅基于 src 包含 close.png 来选择，移除了 onclick 要求。**
  // **警告：这个选择器可能过于宽泛，如果页面其他地方有 src 含 close.png 的非关闭图片，也可能被误点。**
  const closeButtonSelector = 'img[src*="close.png"]';

  const observerCallback = function(mutationsList, observer) {
      for(const mutation of mutationsList) {
          if (mutation.type === 'childList') {
              // 检查是否有新的节点被添加
              mutation.addedNodes.forEach(node => {
                  // 检查添加的节点本身或其子孙节点是否匹配关闭按钮
                  if (node.nodeType === Node.ELEMENT_NODE) {
                      let closeButton = null;
                      if (node.matches(closeButtonSelector)) {
                          closeButton = node;
                      } else if (node.querySelector) { // Element might not have querySelector (e.g., text node)
                          closeButton = node.querySelector(closeButtonSelector);
                      }

                      if (closeButton && closeButton.offsetParent !== null) { // 检查按钮是否可见 (非 display:none 且有尺寸)
                          console.log('麦吉净化：检测到弹窗关闭按钮，尝试自动关闭...');
                          closeButton.click();
                          // 可选：找到后可以断开观察，如果弹窗只出现一次
                          // observer.disconnect();
                          // console.log('麦吉净化：已关闭弹窗并停止监听。');
                      }
                  }
              });
          }
      }
  };

  // 创建一个观察器实例并传入回调函数
  const observer = new MutationObserver(observerCallback);

  // 配置观察选项:
  const config = { childList: true, subtree: true }; // 监听子节点变化及所有后代节点变化

  // 选择目标节点开始观察 (通常是 body)
  const targetNode = document.body;
  if (targetNode) {
      observer.observe(targetNode, config);
      console.log('麦吉净化：已启动弹窗关闭按钮监听器 (基于 src*="close.png")。');
  }

  // 初始检查一次，以防弹窗在脚本运行前已经加载
  const initialCloseButton = document.querySelector(closeButtonSelector);
  if (initialCloseButton && initialCloseButton.offsetParent !== null) {
      console.log('麦吉净化：检测到初始弹窗关闭按钮 (基于 src*="close.png")，尝试自动关闭...');
      initialCloseButton.click();
  }

})();
