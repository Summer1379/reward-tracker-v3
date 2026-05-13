"""
全屏特效层：PyObjC + WKWebView
- 透明 NSPanel 覆盖整个屏幕
- 不抢焦点（NSNonactivatingPanelMask）
- 忽略所有鼠标事件（穿透）
- 通过 evaluateJavaScript 触发 HTML/CSS/JS 特效
"""

import os

try:
    import objc
    from Cocoa import (
        NSPanel,
        NSScreen,
        NSColor,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        NSFloatingWindowLevel,
        NSURL,
    )
    from WebKit import WKWebView, WKWebViewConfiguration
    HAS_OVERLAY = True
except ImportError:
    HAS_OVERLAY = False


# 状态栏窗口级别（24）+ 一些偏移，确保盖在大多数应用之上但低于系统级菜单
_OVERLAY_LEVEL = 24


class EffectsOverlay:
    def __init__(self, html_path):
        if not HAS_OVERLAY:
            self.window = None
            self.webview = None
            return

        screen = NSScreen.mainScreen()
        frame = screen.frame()

        style = (
            NSWindowStyleMaskBorderless
            | NSWindowStyleMaskNonactivatingPanel
        )
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setLevel_(_OVERLAY_LEVEL)
        panel.setIgnoresMouseEvents_(True)        # 关键：穿透
        panel.setHidesOnDeactivate_(False)
        panel.setReleasedWhenClosed_(False)
        # 在所有 Space 显示
        try:
            from Cocoa import (
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
                NSWindowCollectionBehaviorIgnoresCycle,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
            )
            panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorIgnoresCycle
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
        except Exception:
            pass

        # WKWebView 配置
        config = WKWebViewConfiguration.alloc().init()
        webview = WKWebView.alloc().initWithFrame_configuration_(
            panel.contentView().bounds(), config
        )
        webview.setValue_forKey_(False, "drawsBackground")  # 透明背景
        try:
            webview.setUnderPageBackgroundColor_(NSColor.clearColor())
        except Exception:
            pass

        panel.contentView().addSubview_(webview)
        webview.setAutoresizingMask_(0x12)  # width + height resize

        url = NSURL.fileURLWithPath_(html_path)
        webview.loadFileURL_allowingReadAccessToURL_(url, url.URLByDeletingLastPathComponent())

        panel.orderFrontRegardless()

        self.window = panel
        self.webview = webview
        self._ready = False
        # 等待 HTML 加载完成（简单延迟）
        self._js_buffer = []

    def _js_safe(self, s):
        return (
            s.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "")
        )

    def _eval(self, js):
        if not self.webview:
            return
        try:
            self.webview.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass

    def screen_size(self):
        if not self.window:
            return (1920, 1080)
        f = self.window.frame()
        return (int(f.size.width), int(f.size.height))

    def float_text(self, text, x=None, y=None, color="#FFD700"):
        if x is None or y is None:
            sw, sh = self.screen_size()
            x = sw / 2 + (hash(text) % 200 - 100)
            y = sh / 2 + (hash(text) % 100 - 50)
        self._eval(
            f"if(window.fxFloat) fxFloat('{self._js_safe(text)}', {int(x)}, {int(y)}, '{color}');"
        )

    def critical(self, text, x=None, y=None, color="#FFD700"):
        if x is None or y is None:
            sw, sh = self.screen_size()
            x, y = sw / 2, sh / 2
        self._eval(
            f"if(window.fxCritical) fxCritical('{self._js_safe(text)}', {int(x)}, {int(y)}, '{color}');"
        )

    def level_up(self, level):
        self._eval(f"if(window.fxLevelUp) fxLevelUp({int(level)});")

    def achievement(self, title, rarity):
        self._eval(
            f"if(window.fxAchievement) fxAchievement('{self._js_safe(title)}', '{rarity}');"
        )

    def shutdown(self):
        if self.window:
            try:
                self.window.orderOut_(None)
                self.window.close()
            except Exception:
                pass


def make_overlay():
    if not HAS_OVERLAY:
        return None
    html_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "effects.html"
    )
    if not os.path.exists(html_path):
        return None
    try:
        return EffectsOverlay(html_path)
    except Exception:
        return None
