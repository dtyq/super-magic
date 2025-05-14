"""
API路由集中注册模块

该模块负责集中注册所有API路由，包括RESTful API和WebSocket路由，
简化路由管理和维护。
"""
from fastapi import APIRouter

from app.api.routes.chat_history import router as chat_history_router

# 导入所有需要注册的路由器
from app.api.routes.websocket import router as websocket_router

# 创建主路由器，设置统一前缀
api_router = APIRouter(prefix="/api")

# 注册WebSocket路由
api_router.include_router(websocket_router)
# 注册聊天历史路由
api_router.include_router(chat_history_router)

@api_router.get("/health", tags=["base"])
async def health_check():
    """健康检查端点，用于监控服务状态"""
    return {"status": "healthy"}
