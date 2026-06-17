import json
import re
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🛠️ 【配置区域】请在这里填写你的真实 DeepSeek Key
DEEPSEEK_API_KEY = "REDACTED_API_KEY"
# 官方标准请求地址
API_URL = "https://api.deepseek.com"

# 模拟内存数据库
PLAYER_DB = {
    "name": "张铁柱",
    "location": "青云门外门柴房",
    "level": "练气期一层",
    "spirit_power": 10,
}

class ActionRequest(BaseModel):
    user_input: str

@app.get("/player/status")
def get_status():
    return PLAYER_DB

@app.post("/game/action")
async def game_action(request: ActionRequest):
    global PLAYER_DB
    
    system_prompt = f"""
    你是一款文字修仙 MUD 游戏的‘动态地下城主（DM）’。
    请根据玩家输入的任意行动，结合玩家当前的数值状态，客观判定行动结果，并生成一段精彩、具有网文爽感的文字描写。
    
    【当前玩家状态】：
    - 名字：{PLAYER_DB['name']}
    - 所在地点：{PLAYER_DB['location']}
    - 当前境界：{PLAYER_DB['level']}
    - 当前灵力：{PLAYER_DB['spirit_power']}

    【硬性规则】：
    1. 你的每一次回复【必须】严格遵守以下 JSON 格式，不要包含任何 markdown 标记（如 ```json），直接返回纯 JSON 字符串：
    {{
        "story": "此处填写你生成的剧情描写，字数在100字以内。",
        "new_location": "新地点名称",
        "spirit_change": 0
    }}
    2. 玩家不能凭空无敌。
    """

    # 构造原生的 HTTP 请求体
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_input}
        ],
        "stream": False  # 采用最稳妥的一次性接收
    }

    try:
        # 使用 httpx 发送原生网络请求
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(API_URL, headers=headers, json=payload)
            
            # 如果接口报错（如401、402、422），直接打印出最原始的厂商错误原因
            if response.status_code != 200:
                print(f"[DeepSeek 服务器返回错误] 状态码: {response.status_code}, 详情: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=f"DeepSeek 报错: {response.text}")
            
            res_json = response.json()
            
        # 精准提取大模型返回的文本内容
        full_reply = res_json['choices'][0]['message']['content']
        print(f"\n--- [AI 原始返回文本] ---\n{full_reply}\n----------------------------")

        # 后台解析 JSON 并同步玩家数值
        try:
            match = re.search(r'\{.*\}', full_reply, re.DOTALL)
            if match:
                clean_json = match.group(0)
                data = json.loads(clean_json)
                
                # 更新地点
                PLAYER_DB["location"] = data.get("new_location", PLAYER_DB["location"])
                
                # 更新灵力（类型安全防御）
                try:
                    spirit_change = int(data.get("spirit_change", 0))
                except (ValueError, TypeError):
                    spirit_change = 0
                PLAYER_DB["spirit_power"] += spirit_change
                
                print(f"[数据同步成功] 玩家状态已更新: {PLAYER_DB}")
                
                # 兼容前端流式接收，将提取出的文字包裹成生成器返回
                def response_generator():
                    yield data.get("story", "剧情生成失败")
                return StreamingResponse(response_generator(), media_type="text/plain")
            else:
                print("[数据同步失败]: 文本中未能提取到任何合法的 JSON 结构。")
                raise ValueError("未匹配到JSON")
                
        except Exception as parse_err:
            print(f"[数据解析失败]: {parse_err}")
            def backup_generator():
                yield full_reply
            return StreamingResponse(backup_generator(), media_type="text/plain")

    except httpx.RequestError as req_err:
        print(f"[网络请求致命失败]: 无法连接到 DeepSeek 服务器: {req_err}")
        raise HTTPException(status_code=500, detail="网络请求失败")
    except Exception as e:
        print(f"[系统未知内部错误]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
