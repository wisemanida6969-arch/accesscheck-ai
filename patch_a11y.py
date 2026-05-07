"""
Patch Streamlit's bundled index.html to add WCAG 2.4.1 landmark + skip link.
Runs at Docker build time. Failures are logged but do not block the build.
"""
import streamlit as st
import pathlib
import re
import traceback

try:
    p = pathlib.Path(st.__file__).parent / "static" / "index.html"
    print(f"[A11Y] path={p} exists={p.exists()}")
    h = p.read_text(encoding="utf-8")

    if "<!-- A11Y -->" in h:
        print("[A11Y] already patched")
    else:
        # 1) Skip link as first focusable element in <body>
        skip_link = (
            '<!-- A11Y -->'
            '<a href="#main-content" class="skip-link" '
            'style="position:absolute;left:-9999px;top:auto;width:1px;height:1px;'
            'overflow:hidden;background:#1e40af;color:#fff;padding:8px 16px;'
            'z-index:9999;border-radius:4px;text-decoration:none;font-weight:600;" '
            'onfocus="this.style.cssText=\'position:absolute;left:8px;top:8px;'
            'width:auto;height:auto;background:#1e40af;color:#fff;padding:8px 16px;'
            'z-index:9999;border-radius:4px;text-decoration:none;font-weight:600;\'" '
            'onblur="this.style.cssText=\'position:absolute;left:-9999px;\'">'
            'Skip to main content</a>'
        )
        h = h.replace("<body>", "<body>" + skip_link, 1)

        # 2) Add target anchor + landmark role to root div
        h = re.sub(
            r'<div id="root"([^>]*)>',
            r'<a id="main-content" tabindex="-1" '
            r'style="position:absolute;width:1px;height:1px;overflow:hidden;"></a>'
            r'<div id="root"\1 role="main" aria-label="Main content">',
            h,
            count=1,
        )

        p.write_text(h, encoding="utf-8")
        print("[A11Y] patched skip-link + main landmark")

except Exception:
    traceback.print_exc()
    print("[A11Y] ERROR - patch failed, continuing build")
