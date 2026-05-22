import re
import sys
import time
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://toproxylab.com/ru/proksi-dlya-tg"


def fetch_proxy_list() -> List[Tuple[str, int]]:
    """
    Загружает страницу с прокси и вытаскивает IP:порт из <td class="tpl-s5-ip">IP:PORT</td>.
    Возвращает список (ip, port).
    """
    print(f"[INFO] Загружаем список прокси с {LIST_URL} ...")
    try:
        resp = requests.get(LIST_URL, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Не удалось загрузить страницу: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    proxies: List[Tuple[str, int]] = []

    # Ищем все td.tpl-s5-ip
    cells = soup.select("td.tpl-s5-ip")
    if not cells:
        print("[WARN] Не нашли ни одного <td class='tpl-s5-ip'>. Верстка могла измениться.")
        return []

    ip_port_re = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")

    for cell in cells:
        text = cell.get_text(strip=True)
        m = ip_port_re.search(text)
        if m:
            ip = m.group(1)
            port = int(m.group(2))
            proxies.append((ip, port))

    # Удаляем дубликаты, сохраняя порядок
    uniq = list(dict.fromkeys(proxies))
    print(f"[INFO] Найдено {len(uniq)} прокси (ip:port) в td.tpl-s5-ip.")
    return uniq


def test_proxy(ip: str, port: int, timeout: float = 10.0) -> bool:
    """
    Проверяет один SOCKS5-прокси:
    - пытается GET https://api.telegram.org
    - возвращает True, если статус 200, иначе False
    """
    proxy_url = f"socks5://{ip}:{port}"
    proxies = {
        "http": proxy_url,
        "https": proxy_url,
    }
    print(f"[TEST] Пробуем SOCKS5-прокси {proxy_url} ...")

    try:
        resp = requests.get("https://api.telegram.org", proxies=proxies, timeout=timeout)
        print(f"       STATUS: {resp.status_code}")
        if resp.status_code == 200:
            return True
        return False
    except Exception as e:
        print(f"       ERROR: {repr(e)}")
        return False


def main():
    proxies = fetch_proxy_list()
    if not proxies:
        print("[ERROR] Нет прокси для проверки. Выходим.")
        sys.exit(1)

    for ip, port in proxies:
        ok = test_proxy(ip, port)
        # чтобы не заспамить сайт/Telegram, делаем небольшую паузу
        time.sleep(1.0)

        if ok:
            proxy_url = f"socks5://{ip}:{port}"
            print()
            print("[SUCCESS] Найден рабочий SOCKS5-прокси для Telegram:")
            print("          TELEGRAM_PROXY_URL =", proxy_url)
            print("          Пропиши его в settings.py и перезапусти бота.")
            return

    print()
    print("[FAIL] Не удалось найти рабочий прокси из списка. Попробуй позже или используй другой источник.")


if __name__ == "__main__":
    main()