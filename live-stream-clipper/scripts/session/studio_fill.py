# usage: python3 studio_fill.py <video.mp4> <meta.json> <cover.jpg> -> JS for playwright-cli run-code (full Studio upload)
import json, os, sys
from pathlib import Path
_cid = Path.home() / '.config/live-clipper/channel_id'
CHANNEL = os.environ.get('YT_CHANNEL_ID') or (_cid.read_text().strip() if _cid.exists() else sys.exit('set YT_CHANNEL_ID or write it to ~/.config/live-clipper/channel_id'))
video, meta, cover = sys.argv[1:4]
m = json.load(open(meta))
J = json.dumps
print(f"""async page => {{
  page.on('dialog', dg => dg.accept().catch(() => {{}}));
  const fresh = await page.getByRole('button', {{name: 'Select files'}}).isVisible().catch(() => false);
  if (!fresh) {{
  await page.goto('https://studio.youtube.com/channel/{CHANNEL}/videos/short');
  await page.waitForTimeout(4000);
  for (let i = 0; i < 3; i++) {{
    const c = page.locator('ytcp-dialog:visible, tp-yt-paper-dialog:visible').getByRole('button', {{name: /^Close$/}});
    if (await c.count()) {{ await c.first().click().catch(() => {{}}); await page.waitForTimeout(800); }} else break;
  }}
  await page.keyboard.press('Escape').catch(() => {{}});
  await page.getByRole('button', {{name: 'Create'}}).first().click();
  await page.waitForTimeout(1200);
  await page.getByRole('menuitem', {{name: 'Upload videos'}}).click();
  }}
  const d = page.locator('ytcp-uploads-dialog');
  await d.locator('input[type=file]').first().setInputFiles({J(video)});
  await d.locator('#title-textarea #textbox').waitFor({{timeout: 60000}});
  await page.waitForTimeout(4000);
  const lim = (await d.innerText()).match(/[^\\n]*(daily upload limit|limit reached)[^\\n]*/i);
  if (lim) return 'LIMIT ' + lim[0];
  await d.locator('#title-textarea #textbox').click(); await page.keyboard.press('Meta+A'); await page.keyboard.press('Backspace');
  await page.keyboard.type({J(m['title'])});
  await d.locator('#description-textarea #textbox').click(); await page.keyboard.type({J(m['description'])});
  // custom thumbnail skipped: Studio demands 'advanced features' verification; cover is burned into the video
  await page.waitForTimeout(500);
  const adv = page.getByRole('button', {{name: 'Cancel'}});
  if (await page.getByText('Get advanced features').isVisible().catch(() => false)) await adv.last().click();
  const k = d.getByText("No, it's not made for kids", {{exact: true}}); await k.scrollIntoViewIfNeeded(); await k.click();
  await page.waitForTimeout(800);
  if (await d.locator('tp-yt-paper-radio-button[name=VIDEO_MADE_FOR_KIDS_NOT_MFK]').getAttribute('aria-checked') !== 'true') return 'STUDIO_FAIL kids-radio';
  for (let i = 0; i < 3; i++) {{ await d.locator('#next-button').click(); await page.waitForTimeout(2000); }}
  const pub = d.locator('tp-yt-paper-radio-button[name=PUBLIC]');
  await pub.locator('#radioContainer, #onRadio, #offRadio').first().click().catch(async () => {{ await pub.click(); }});
  await page.waitForTimeout(800);
  if (await pub.getAttribute('aria-checked') !== 'true') return 'STUDIO_FAIL public-radio';
  for (let i = 0; i < 300; i++) {{
    const t = await d.innerText();
    if (/Checks complete|Upload complete|Processing (will|up to)|SD|HD/i.test(t) && !/Uploading \\d/.test(t)) break;
    await page.waitForTimeout(2000);
  }}
  await d.locator('#done-button').click(); await page.waitForTimeout(8000);
  const body = await page.locator('body').innerText();
  const ok = /(Video|Short) published/i.test(body);
  const vm = body.match(/https:\\/\\/youtube\\.com\\/shorts\\/[\\w-]+/);
  const vid = vm ? vm[0] : '';
  try {{ await page.getByRole('button', {{name: 'Close'}}).last().click(); }} catch (e) {{}}
  return (ok ? 'STUDIO_UPLOADED ' : 'STUDIO_UNSURE ') + (vid || '');
}}""")
