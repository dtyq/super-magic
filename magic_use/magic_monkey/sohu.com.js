// ==UserScript==
// @name         麦吉 搜狐 超净化
// @namespace    https://dtyq.com/
// @version      1.0
// @description  清理搜狐网站页面，只保留文章内容，移除广告和其他干扰元素
// @author       cc, cc@dtyq.com
// @match        *://www.sohu.com/a/*
// @grant        none
// ==/UserScript==

(function() {
  'use strict';

  // 找到具有 data-spm="content" 属性的元素
  const contentElement = document.querySelector('div[data-spm="content"]');

  // 确保元素存在
  if (!contentElement) {
    console.error('未找到 data-spm="content" 的元素');
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

  // 居中定位目标元素
  contentElement.style.position = 'absolute';
  contentElement.style.left = '50%';
  contentElement.style.transform = 'translate(-50%, 0)';
  contentElement.style.zIndex = '9999';
})();
