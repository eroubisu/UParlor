"""登录与版本检查"""

from __future__ import annotations

from ..messages import LoginPrompt, LoginSuccess


def _on_login_prompt(parsed, app, screen, st):
    login = screen.get_module('login')
    if login and hasattr(login, 'add_message'):
        login.add_message(parsed.text)
    else:
        st.cmd.add_line(parsed.text)


def _on_login_success(parsed, app, screen, st):
    screen.logged_in = True
    st.cmd.add_line(parsed.text)
    login = screen.get_module('login')
    if login:
        login.display = False
    screen.call_later(screen._rebuild_to_game_layout)


def handle_version_check(app, screen, latest: str):
    """服务器下发最新客户端版本号，与本地对比"""
    if not latest:
        return
    try:
        import re
        from ...config import VERSION, M_DIM, M_END

        def _ver_tuple(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in re.findall(r'\d+', v.split('.dev')[0]))

        current = VERSION or "0.0.0"
        if _ver_tuple(latest) > _ver_tuple(current):
            login = screen.get_module('login')
            msg = f"{M_DIM}发现新版本 v{latest}（当前 v{current}），请更新: pip install -U uparlor{M_END}"
            if login and hasattr(login, 'add_message'):
                login.add_message(msg)
            else:
                screen.state.cmd.add_line(msg)
    except Exception:
        pass


HANDLERS = {
    LoginPrompt: _on_login_prompt,
    LoginSuccess: _on_login_success,
}
