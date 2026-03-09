# portal_client.py

import time
from playwright.sync_api import sync_playwright
from config import PORTAL_URL, INPUT_SELECTOR, ANSWER_SELECTOR, HEADLESS


class PortalClient:
    """
    Inzent AI 웹 UI를 Playwright로 조작해서
    질문을 보내고 답변 텍스트를 가져오는 클라이언트.
    """

    def __init__(self, headless: bool = HEADLESS):
        self.headless = headless

    def ask(self, question: str) -> str:
        """
        단일 질문을 포털에 던지고, 답변 텍스트를 반환.
        (질문은 웹 UI textarea에 그대로 입력됨)
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx = browser.new_context()
            page = ctx.new_page()

            # 1) 포털 페이지 접속
            page.goto(PORTAL_URL)
            time.sleep(3)  # 초기 로딩 대기 (필요하면 조정)

            # 2) 질문 입력 + Enter
            page.fill(INPUT_SELECTOR, question)
            page.keyboard.press("Enter")

            # 3) 답변 추출
            answer_text = self._get_answer(page)

            browser.close()

        return answer_text.strip()

    def _get_answer(self, page) -> str:
        try:
            # 답변 영역이 렌더링될 때까지 대기
            page.wait_for_selector(ANSWER_SELECTOR, timeout=15000)
        except Exception:
            return ""

        elem = page.query_selector(ANSWER_SELECTOR)
        if not elem:
            return ""

        return elem.inner_text().strip()
