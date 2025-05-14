// ==UserScript==
// @name         麦吉 东方财富财富号 超净化
// @namespace    https://dtyq.com/
// @version      1.1
// @description  清理东方财富财富号网站页面，聚焦文章内容，移除干扰元素。
// @author       cc, cc@dtyq.com
// @match        *://caifuhao.eastmoney.com/news/*
// @grant        none
// ==/UserScript==

(function() {
  'use strict';

  // --- 1. 定位核心内容元素 ---
  // 优先尝试通用选择器，失败则尝试更精确的选择器
  let contentElement = document.querySelector('div.article.page-article') ||
                       document.querySelector('#main > div.grid_wrapper > div.grid > div.g_content > div.article.page-article');

  // 如果两种方式都找不到，则退出脚本
  if (!contentElement) {
    console.error('麦吉净化脚本：未能找到目标文章元素。');
    return;
  }

  // --- 2. 定义保留规则 ---
  // 判断一个元素是否应该保留：是目标元素本身或其内部元素
  const shouldKeepVisible = (element) => {
    return element === contentElement || contentElement.contains(element);
  };

  // --- 3. 遍历并收集需要隐藏的元素 ---
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_ELEMENT, // 只关心元素节点
    null,
    false
  );

  const elementsToHide = [];
  let currentNode = walker.nextNode();
  while (currentNode) {
    // 如果当前节点不应保留，则添加到待隐藏列表
    if (!shouldKeepVisible(currentNode)) {
      elementsToHide.push(currentNode);
    }
    currentNode = walker.nextNode();
  }

  // --- 4. 统一执行隐藏 ---
  // 批量隐藏可以略微提高性能，减少页面重绘/重排次数
  elementsToHide.forEach(element => {
    // 安全起见，再次确认不隐藏 body 和 html (虽然理论上 shouldKeepVisible 会排除)
    if (element !== document.body && element !== document.documentElement) {
        element.style.display = 'none';
        element.style.visibility = 'hidden';
    }
  });

  // --- 5. 确保目标元素及其所有祖先可见 ---
  // 由于之前的隐藏操作可能影响到目标元素的祖先，需要强制恢复它们的可见性
  let ancestor = contentElement;
  while (ancestor && ancestor !== document.documentElement) { // 向上遍历直到<html>的父节点(null)
    ancestor.style.display = ''; // 清除可能存在的 display:none
    ancestor.style.visibility = 'visible'; // 确保可见

    // 恢复 body 和 html 的默认滚动行为 (如果之前被隐藏)
    if (ancestor === document.body || ancestor === document.documentElement) {
        ancestor.style.overflow = '';
    }
    ancestor = ancestor.parentElement;
  }
  // 单独确保 html 元素可见 (循环到此结束)
  if (document.documentElement) {
      document.documentElement.style.display = '';
      document.documentElement.style.visibility = 'visible';
      document.documentElement.style.overflow = '';
  }


  // --- 6. 应用样式，美化并居中目标元素 ---
  // 使用 Flexbox 在父元素上进行居中
  const parentElement = contentElement.parentElement;
  if (parentElement) {
    parentElement.style.display = 'flex';
    parentElement.style.justifyContent = 'center'; // 水平居中
    parentElement.style.alignItems = 'flex-start';  // 垂直顶部对齐
    parentElement.style.minHeight = '100vh';       // 父元素至少撑满视口高度
    parentElement.style.padding = '40px 10px';     // 父元素上下内边距40px，左右10px
    parentElement.style.boxSizing = 'border-box';  // padding 不增加父元素尺寸
    parentElement.style.width = '100%';          // 父元素占满可用宽度
  }

  // 设置目标元素自身样式
  Object.assign(contentElement.style, {
    display: 'block',
    width: '90%',            // 稍微加宽一点以适应父元素的左右padding
    maxWidth: '800px',
    margin: '0',             // 移除外边距，由父 Flexbox 控制
    padding: '25px 30px',    // 内边距
    backgroundColor: 'white',
    boxShadow: '0 3px 12px rgba(0,0,0,0.1)', // 调整阴影
    border: '1px solid #eee', // 加个细边框
    borderRadius: '4px',      // 轻微圆角
    // 清理可能残留的定位和尺寸约束
    position: '',
    left: '',
    top: '',
    transform: '',
    zIndex: '',
    height: '',
    overflowY: ''
  });

  console.log('麦吉 东方财富财富号 超净化脚本优化版运行完毕');
})();
