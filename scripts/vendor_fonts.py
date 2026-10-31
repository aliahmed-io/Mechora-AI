"""Vendor Google Fonts and their OFL licenses for an offline local application."""
from pathlib import Path
import re
import httpx
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'public'/'fonts';DEST.mkdir(exist_ok=True)
url='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;450;500;550;600;650;700&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500&display=swap'
with httpx.Client(follow_redirects=True,timeout=30) as client:
    css=client.get(url).raise_for_status().text
    urls=list(dict.fromkeys(re.findall(r'url\((https://[^)]+)\)',css)))
    for i,source in enumerate(urls):
        ext=source.split('?')[0].rsplit('.',1)[-1]
        name=f'mechora-font-{i}.{ext}'
        (DEST/name).write_bytes(client.get(source).raise_for_status().content)
        css=css.replace(source,f'/fonts/{name}')
    (ROOT/'app'/'fonts.css').write_text(css,encoding='utf-8')
    for family in ['dmsans','instrumentserif','jetbrainsmono']:
        result=client.get(f'https://raw.githubusercontent.com/google/fonts/main/ofl/{family}/OFL.txt')
        if result.is_success:(DEST/f'{family}-OFL.txt').write_text(result.text,encoding='utf-8')
print(f'Vendored {len(urls)} font files.')
