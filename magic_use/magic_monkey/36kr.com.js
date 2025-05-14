// ==UserScript==
// @name         麦吉 36氪 超净化
// @namespace    https://dtyq.com/
// @version      1.0
// @description  清理36氪网站页面，只保留文章内容区域，提供更清爽的阅读体验
// @author       cc, cc@dtyq.com
// @match        *://36kr.com/p/*
// @grant        none
// ==/UserScript==

(function() {
  'use strict';

  // 找到具有 .article-content 类的元素
  const contentElement = document.querySelector('.article-content');

  // 确保元素存在
  if (!contentElement) {
    console.error('未找到 .article-content 元素');
    return;
  }

  // 创建一个函数检查元素是否应该保留显示
  const shouldKeepVisible = (element) => {
    return element === contentElement ||
           element.contains(contentElement) ||
           contentElement.contains(element) ||
           element === document.body ||
           element === document.documentElement;
  };

  // 使用 TreeWalker API 高效遍历 DOM 树
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_ELEMENT,
    null,
    false
  );

  // 保存找到的需要隐藏的元素
  const elementsToHide = [];

  // 开始遍历
  let currentNode = walker.nextNode();
  while (currentNode) {
    if (!shouldKeepVisible(currentNode)) {
      elementsToHide.push(currentNode);
    }
    currentNode = walker.nextNode();
  }

  // 统一隐藏元素，减少重排
  elementsToHide.forEach(element => {
    element.style.display = 'none';
  });

  // 确保目标元素可见
  contentElement.style.display = 'block';

  // 确保从body到目标元素的路径上所有元素可见
  let parent = contentElement.parentElement;
  while (parent) {
    parent.style.display = '';
    parent = parent.parentElement;
  }

  // 确保 body 和 html 可以正常滚动
  document.body.style.overflow = 'auto';
  document.documentElement.style.overflow = 'auto';
  document.body.style.height = 'auto';
  document.documentElement.style.height = 'auto';

  // 创建一个容器来包裹内容
  const container = document.createElement('div');
  container.style.width = '100%';
  container.style.maxWidth = '800px';
  container.style.margin = '0 auto';
  container.style.padding = '20px';
  container.style.backgroundColor = '#fff';
  container.style.boxSizing = 'border-box';

  // 将内容移动到新容器中
  const parent2 = contentElement.parentElement;
  parent2.insertBefore(container, contentElement);
  container.appendChild(contentElement);

  // 重置内容样式，使用相对定位而非绝对定位
  contentElement.style.position = 'relative';
  contentElement.style.left = 'auto';
  contentElement.style.transform = 'none';
  contentElement.style.zIndex = '9999';
  contentElement.style.width = '100%';

  // 清理页面其他位置可能干扰滚动的样式
  const elementsWithFixedPosition = document.querySelectorAll('[style*="position: fixed"]');
  elementsWithFixedPosition.forEach(element => {
    if (!shouldKeepVisible(element)) {
      element.style.display = 'none';
    }
  });
})();
