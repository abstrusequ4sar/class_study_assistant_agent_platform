"""通过 Chrome DevTools Protocol 采集新版汇报所需的真实界面。"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.request
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets" / "screenshots"
ORIGIN = "http://localhost:5173"


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.counter = 0

    async def call(self, method: str, params: dict | None = None):
        self.counter += 1
        call_id = self.counter
        await self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == call_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str):
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        return result.get("result", {}).get("value")


def page_ws_url() -> str:
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list") as response:
        pages = json.load(response)
    return next(page["webSocketDebuggerUrl"] for page in pages if page.get("type") == "page")


async def navigate(cdp: CDP, route: str, wait_seconds: float = 3.0):
    await cdp.call("Page.navigate", {"url": f"{ORIGIN}/#{route}"})
    await asyncio.sleep(wait_seconds)


async def screenshot(cdp: CDP, filename: str):
    result = await cdp.call(
        "Page.captureScreenshot",
        {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
    )
    (OUT / filename).write_bytes(base64.b64decode(result["data"]))


async def main():
    token = os.environ["DEMO_TOKEN"]
    OUT.mkdir(parents=True, exist_ok=True)

    async with websockets.connect(page_ws_url(), max_size=32 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        await cdp.call("Page.enable")
        await cdp.call("Runtime.enable")
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )

        await cdp.call("Page.navigate", {"url": ORIGIN})
        await asyncio.sleep(2)
        await cdp.evaluate(f"localStorage.setItem('token', {json.dumps(token)})")

        if os.getenv("CAPTURE_MATERIAL_ONLY") == "1":
            await navigate(cdp, "/courses/3", 3)
            await screenshot(cdp, "material_search.png")
            print(json.dumps({"files": ["material_search.png"]}, ensure_ascii=False))
            return

        await navigate(cdp, "/courses/3/chat", 4)
        await cdp.evaluate(
            """
            (() => {
              const list = document.querySelector('.msg-list');
              if (list) list.scrollTop = list.scrollHeight;
            })()
            """
        )
        await asyncio.sleep(1)
        await screenshot(cdp, "agent_sources_clickable.png")

        clicked = await cdp.evaluate(
            """
            (() => {
              const tag = document.querySelector('.citation-tag');
              if (!tag) return false;
              tag.click();
              return true;
            })()
            """
        )
        if not clicked:
            raise RuntimeError("没有找到可点击的来源标签")
        await asyncio.sleep(4)
        route = await cdp.evaluate("location.hash")
        if "material_id=" not in (route or ""):
            raise RuntimeError(f"来源跳转未生效: {route}")
        await screenshot(cdp, "source_jump.png")

        await navigate(cdp, "/courses/3", 3)
        await screenshot(cdp, "material_search.png")
        await cdp.evaluate(
            """
            (() => {
              const tab = [...document.querySelectorAll('.el-tabs__item')]
                .find((node) => node.textContent.trim() === '知识点整理');
              if (tab) tab.click();
            })()
            """
        )
        await asyncio.sleep(1)
        await cdp.evaluate(
            """
            (() => {
              const button = [...document.querySelectorAll('button')]
                .find((node) => node.textContent.includes('生成知识点提纲'));
              if (button) button.click();
            })()
            """
        )
        for _ in range(45):
            await asyncio.sleep(2)
            state = await cdp.evaluate(
                """
                (() => ({
                  text: document.querySelector('.markdown')?.innerText?.length || 0,
                  loading: [...document.querySelectorAll('button')]
                    .some((node) => node.textContent.includes('生成中'))
                }))()
                """
            )
            if state and state["text"] > 80 and not state["loading"]:
                break
        await screenshot(cdp, "knowledge_summary.png")

    print(json.dumps({"files": sorted(path.name for path in OUT.glob("*.png"))}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
