"""Exercise the actual retail UI and guarded mock backend with a real Chromium browser.

Only LLM responses are scripted. Approval buttons, sessions, business checks,
semantic retrieval, SSE and inventory verification run through repository code.
Artifacts contain fictional fixtures, never production requests or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"


def state():
    with urllib.request.urlopen(API + "/__test__/state", timeout=2) as response:
        return json.load(response)


def wait_for_server(process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Isolated browser fixture exited")
        try:
            if state().get("fixture"):
                return
        except (OSError, ValueError):
            time.sleep(0.1)
    raise TimeoutError("Fixture readiness deadline")


def visible_button(page, name):
    return page.get_by_role("button", name=name, exact=True).filter(visible=True).first


def run_case(browser, root_url, out, *, locale, width, action, degraded):
    key = f"{locale}-{width}-{action}-{'degraded' if degraded else 'normal'}"
    log = (out / f"{key}.server.log").open("w")
    command = [sys.executable, str(ROOT / "scripts/semantic_browser_server.py")]
    if degraded:
        command.append("--degraded")
    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 500 else 844}, locale=locale
    )
    page = context.new_page()
    page.set_default_timeout(15_000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # External product photos are irrelevant to this control-flow test.
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if re.match(r"^https?://(localhost|127\.0\.0\.1)(:|/)", route.request.url)
            else route.abort()
        ),
    )
    row = {
        "case": key,
        "locale": locale,
        "viewport_width": width,
        "action": action,
        "scripted_models": True,
        "real_model_calls": 0,
    }
    try:
        wait_for_server(process)
        page.goto(root_url, wait_until="domcontentloaded")
        visible_button(page, "中文" if locale == "zh-CN" else "EN").click()
        if width < 1024:
            # The mobile header uses the visible Assistant label; desktop has Show/Hide aria labels.
            page.locator("header").get_by_role(
                "button", name="助手" if locale == "zh-CN" else "Assistant", exact=True
            ).click()
        box = page.get_by_role(
            "textbox",
            name="向商家助手发送消息" if locale == "zh-CN" else "Message the merchant assistant",
        )
        expect(box).to_be_visible()
        box.fill(
            "请检查 AR-2102，按30天覆盖量计算补货并暂存预览，等待卡片批准。"
            if locale == "zh-CN"
            else "Restock AR-2102 for 30 days of coverage, stage a preview, and wait for card approval."
        )
        box.press("Enter")
        approve_name = "批准" if locale == "zh-CN" else "Approve"
        dismiss_name = "忽略" if locale == "zh-CN" else "Dismiss"
        expect(visible_button(page, approve_name)).to_be_enabled()
        assert state()["stock"] == 12 and state()["pending"] == 1
        page.screenshot(path=str(out / f"{key}-preview.png"), full_page=True)
        visible_button(page, approve_name if action == "apply" else dismiss_name).click()
        expected_stock = 90 if action == "apply" else 12
        expected_phase = "SUCCESS" if action == "apply" else "DECLINED"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and expected_phase not in state()["phases"]:
            page.wait_for_timeout(100)
        final_state = state()
        assert final_state["stock"] == expected_stock and expected_phase in final_state["phases"]
        if width < 1024:
            page.get_by_role(
                "button", name="隐藏助手" if locale == "zh-CN" else "Hide assistant", exact=True
            ).filter(visible=True).last.click()
        visible_button(page, "推理调试" if locale == "zh-CN" else "Reasoning").click()
        panel = page.get_by_test_id("semantic-context-panel")
        expect(panel).to_be_visible()
        if degraded:
            expect(panel).to_contain_text("SEMANTIC_BUDGET_EXCEEDED")
        else:
            expect(page.get_by_test_id("semantic-snapshot-state")).to_contain_text(
                "历史上下文" if locale == "zh-CN" else "Historical context"
            )
            panel.locator(
                "summary",
                has_text="为什么包含这些定义？"
                if locale == "zh-CN"
                else "Why are these definitions included?",
            ).click()
            expect(panel).to_contain_text("waiting_for_host")
        panel.scroll_into_view_if_needed()
        page.screenshot(path=str(out / f"{key}-semantic.png"), full_page=True)
        panel.screenshot(path=str(out / f"{key}-panel.png"))
        # Wide PG canvases may scroll inside their containers, never overflow the page.
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2")
        assert not errors, errors
        row.update(passed=True, state=final_state)
    except Exception as error:
        row.update(
            passed=False,
            error_type=type(error).__name__,
            error=str(error)[:1800],
            browser_errors=errors,
        )
        page.screenshot(path=str(out / f"{key}-failure.png"), full_page=True)
    finally:
        context.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3100")
    parser.add_argument("--out", type=Path, default=Path("runtime/browser-acceptance"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as p:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        browser = p.chromium.launch(**({"executable_path": executable} if executable else {}))
        for locale, width, action, degraded in (
            ("en", 1440, "apply", False),
            ("zh-CN", 1440, "discard", False),
            ("zh-CN", 390, "apply", False),
            ("en", 390, "discard", False),
            ("en", 1440, "apply", True),
            ("zh-CN", 390, "discard", True),
        ):
            rows.append(
                run_case(
                    browser,
                    args.url,
                    args.out,
                    locale=locale,
                    width=width,
                    action=action,
                    degraded=degraded,
                )
            )
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        browser.close()
    report = {
        "passed": all(row["passed"] for row in rows),
        "cases": rows,
        "scope": "Real browser and mock business backend; LLM decisions scripted. Not a live model evaluation.",
        "real_model_calls": 0,
    }
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
