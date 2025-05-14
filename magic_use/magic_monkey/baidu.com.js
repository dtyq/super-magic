// ==UserScript==
// @name         麦吉 百度搜索 超净化
// @namespace    https://dtyq.com/
// @version      1.0
// @description  清理百度搜索页面，移除右侧广告、底部用户信息栏和页脚，提供纯净的搜索体验
// @author       cc, cc@dtyq.com
// @match        *://www.baidu.com/s*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // 创建一个函数来移除特定元素
    function removeElements() {
        // 移除右侧内容（广告等）
        const rightContent = document.getElementById('content_right');
        if (rightContent) {
            rightContent.remove();
            console.log('已移除右侧内容框');
        }

        // 移除底部用户信息栏
        const userBar = document.getElementById('u');
        if (userBar) {
            userBar.remove();
            console.log('已移除底部用户信息栏');
        }

        // 移除页脚
        const footerElements = document.querySelectorAll('[tpl="app/footer"]');
        footerElements.forEach(element => {
            element.remove();
            console.log('已移除页脚元素');
        });
    }

    removeElements();
})();
