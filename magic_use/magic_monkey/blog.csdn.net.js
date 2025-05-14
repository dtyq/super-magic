// ==UserScript==
// @name         麦吉 CSDN博客 超净化
// @namespace    https://dtyq.com/
// @version      1.0
// @description  清理CSDN博客页面，去除广告、登录提示等干扰内容，提供纯净的阅读体验
// @author       cc, cc@dtyq.com
// @match        *://blog.csdn.net/*/article/details/*
// @grant        none
// ==/UserScript==

(function() {
  'use strict';

  // 定义一个用于清理CSDN博客页面的函数
  function cleanupCSDN() {
    // 获取主要内容区域
    const mainContent = document.querySelector("#mainBox > main > div.blog-content-box");

    if (!mainContent) {
      console.log("未找到主要内容区域，可能不在CSDN博客页面上");
      return;
    }

    // 创建一个函数检查元素是否应该保留显示
    const shouldKeepVisible = (element) => {
      return element === mainContent ||
             element.contains(mainContent) ||
             mainContent.contains(element) ||
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
    mainContent.style.display = 'block';

    // 确保从body到目标元素的路径上所有元素可见
    let parent = mainContent.parentElement;
    while (parent) {
      parent.style.display = 'block';
      parent = parent.parentElement;
    }

    // 确保 body 和 html 可以正常滚动
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
    document.body.style.height = 'auto';
    document.documentElement.style.height = 'auto';
    document.body.style.backgroundColor = '#f5f5f5';

    // 创建一个容器来包裹内容
    const container = document.createElement('div');
    container.style.width = '100%';
    container.style.maxWidth = '900px';
    container.style.margin = '0 auto';
    container.style.padding = '20px';
    container.style.backgroundColor = '#fff';
    container.style.boxSizing = 'border-box';
    container.style.boxShadow = '0 0 10px rgba(0, 0, 0, 0.1)';

    // 将内容移动到新容器中
    const parent2 = mainContent.parentElement;
    parent2.insertBefore(container, mainContent);
    container.appendChild(mainContent);

    // 重置内容样式，使用相对定位而非绝对定位
    mainContent.style.position = 'relative';
    mainContent.style.left = 'auto';
    mainContent.style.transform = 'none';
    mainContent.style.zIndex = '1';
    mainContent.style.width = '100%';
    mainContent.style.margin = '0';
    mainContent.style.padding = '0';
    mainContent.style.boxShadow = 'none';

    // 确保内容中的所有元素都可见
    const allContentElements = mainContent.querySelectorAll('*');
    allContentElements.forEach(element => {
      element.style.display = '';
    });

    // 清理页面其他位置可能干扰滚动的样式
    const elementsWithFixedPosition = document.querySelectorAll('[style*="position: fixed"]');
    elementsWithFixedPosition.forEach(element => {
      if (!shouldKeepVisible(element)) {
        element.style.display = 'none';
      }
    });

    console.log("CSDN页面已净化，仅显示主要内容");
  }

  // 在DOM加载完成后执行清理
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", cleanupCSDN);
  } else {
    cleanupCSDN();
  }

  // 在页面完全加载后再次执行，以应对延迟加载的元素
  window.addEventListener("load", cleanupCSDN);
})();
